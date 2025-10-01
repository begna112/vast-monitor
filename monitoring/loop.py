from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    retry_if_exception_type,
)

from Classes.app_config import AppConfig
from Classes.vast_machine import VastMachine
from monitoring.state import (
    StatePaths,
    ensure_state_dirs,
    load_all_rental_snapshots,
    load_rental_snapshot,
    load_machine_snapshot,
    save_machine_snapshot,
    save_rental_snapshot,
)
from monitoring.rentals import process_rental_changes, seed_sessions_for_current_occupancy
from notifications.dispatcher import NotificationManager


def get_machines(vastai, config: AppConfig, logger: logging.Logger) -> list[VastMachine]:
    def _fetch_once() -> list[VastMachine]:
        raw = vastai.show_machines()
        machines = [VastMachine(**item) for item in raw["machines"]]
        machines = [machine for machine in machines if machine.machine_id in config.machine_ids]
        if config.debug:
            for machine in machines:
                logger.debug(json.dumps(machine.model_dump()))
        return machines

    retry_logger = logging.getLogger("VastMonitor")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(retry_logger, logging.WARNING),
        reraise=True,
    )
    def _fetch_with_retry() -> list[VastMachine]:
        return _fetch_once()

    try:
        return _fetch_with_retry()
    except RetryError as exc:
        cause = exc.last_attempt.exception() or exc
        if config.debug:
            logger.exception("Failed to fetch machines after retries: %s", cause)
        else:
            logger.error(
                "Failed to fetch machines after retries: %s: %s",
                cause.__class__.__name__,
                cause,
            )
        return []


def start_monitoring(
    *,
    config: AppConfig,
    logger: logging.Logger,
    vastai,
    paths: StatePaths,
    notifier: Optional[NotificationManager],
) -> None:
    ensure_state_dirs(paths)
    error_ping_minutes = int(config.notify.error_ping_interval_minutes)

    try:
        machines = get_machines(vastai, config, logger)
        full_data = load_all_rental_snapshots(paths)

        for machine in machines:
            key = str(machine.machine_id)
            existing_entry = isinstance(full_data, dict) and key in full_data
            if not existing_entry:
                seed_sessions_for_current_occupancy(machine, paths=paths, logger=logger)
            else:
                snap = full_data.get(key, {})
                gmap = snap.get("gpus") if isinstance(snap, dict) else None
                sessions = snap.get("sessions") if isinstance(snap, dict) else None
                has_stored_sessions = any(
                    isinstance(sdata, dict) and sdata.get("status") == "stored"
                    for sdata in (sessions or {}).values()
                )
                if (
                    not gmap
                    and not has_stored_sessions
                    and any(token != "x" for token in machine.gpu_occupancy.split())
                ):
                    seed_sessions_for_current_occupancy(machine, paths=paths, logger=logger)

        if config.notify.on_startup_existing and notifier is not None:
            items = []
            for machine in machines:
                try:
                    snapshot = load_rental_snapshot(paths, machine.machine_id)
                except Exception:
                    snapshot = {"sessions": {}, "gpu_occupancy": machine.gpu_occupancy, "gpu_name": machine.gpu_name}
                if isinstance(snapshot, dict):
                    snapshot.setdefault("gpu_name", machine.gpu_name)
                items.append(
                    {
                        "machine_id": machine.machine_id,
                        "num_gpus": machine.num_gpus,
                        "gpu_occupancy": machine.gpu_occupancy,
                        "gpu_name": machine.gpu_name,
                        "snapshot": snapshot,
                    }
                )

            try:
                for entry in items:
                    mid = entry["machine_id"]
                    snapshot = entry["snapshot"]
                    sessions = snapshot.get("sessions", {}) if isinstance(snapshot, dict) else {}
                    for sid, session in sessions.items():
                        if session.get("end_time") is None:
                            status = (session.get("status") or "running").lower()
                            rental_type = session.get("gpu_type") or session.get("type", "?")
                            rate = 0.0
                            try:
                                for segment in reversed(session.get("gpu_segments", []) or []):
                                    if segment.get("end") is None:
                                        rate = float(segment.get("rate", 0.0) or 0.0)
                                        break
                                if not rate:
                                    rate = float(session.get("gpu_contracted_rate", 0.0) or 0.0)
                            except Exception:
                                rate = float(session.get("gpu_contracted_rate", 0.0) or 0.0)
                            gpus = session.get("gpus", [])
                            if status == "stored":
                                logger.info(
                                    "Detected stored session at startup (inactive): machine %s, session %s, stored gpus %s",
                                    mid,
                                    sid,
                                    gpus,
                                )
                            else:
                                logger.info(
                                    "Detected ongoing rental at startup: machine %s, session %s, type %s, rate %s, gpus %s",
                                    mid,
                                    sid,
                                    rental_type,
                                    rate,
                                    gpus,
                                )
                    machine_obj = next((m for m in machines if m.machine_id == mid), None)
                    err_desc = getattr(machine_obj, "error_description", None) if machine_obj else None
                    if err_desc:
                        minutes = error_ping_minutes
                        last = snapshot.get("last_error_notified_at") if isinstance(snapshot, dict) else None
                        allow = True
                        if last:
                            try:
                                last_dt = datetime.fromisoformat(last)
                                allow = (datetime.now(timezone.utc) - last_dt).total_seconds() >= minutes * 60
                            except Exception:
                                allow = True
                        if allow:
                            logger.error("Machine %s error at startup: %s", mid, err_desc)
                            notifier.send_error(machine_id=mid, error=err_desc)
                            snapshot["last_error_notified_at"] = datetime.now(timezone.utc).isoformat()
                            save_rental_snapshot(paths, mid, snapshot)
            except Exception:
                pass

            notifier.send_startup_summary(items=items)
    except Exception as exc:
        if config.debug:
            logger.exception("Failed conditional seeding of rental snapshots: %s", exc)
        else:
            logger.error(
                "Failed conditional seeding of rental snapshots: %s: %s",
                exc.__class__.__name__,
                exc,
            )

    try:
        while True:
            try:
                machines = get_machines(vastai, config, logger)
                for new in machines:
                    try:
                        old = load_machine_snapshot(paths, new)
                    except FileNotFoundError:
                        logger.info("Initial snapshot for machine %s, saving.", new.machine_id)
                        save_machine_snapshot(paths, new)
                        try:
                            full_data = load_all_rental_snapshots(paths)
                            key = str(new.machine_id)
                            if not (isinstance(full_data, dict) and key in full_data):
                                seed_sessions_for_current_occupancy(new, paths=paths, logger=logger)
                            else:
                                snap = full_data.get(key, {})
                                gmap = snap.get("gpus") if isinstance(snap, dict) else None
                                sessions = snap.get("sessions") if isinstance(snap, dict) else None
                                has_stored_sessions = any(
                                    isinstance(sdata, dict) and sdata.get("status") == "stored"
                                    for sdata in (sessions or {}).values()
                                )
                                if (
                                    not gmap
                                    and not has_stored_sessions
                                    and any(token != "x" for token in new.gpu_occupancy.split())
                                ):
                                    seed_sessions_for_current_occupancy(new, paths=paths, logger=logger)
                        except Exception as exc_seed:
                            logger.exception(
                                "Failed seeding sessions for machine %s: %s",
                                new.machine_id,
                                exc_seed,
                            )
                        continue

                    monitored_fields = (
                        "verification",
                        "clients",
                        "error_description",
                        "listed",
                        "gpu_occupancy",
                        "current_rentals_running",
                        "current_rentals_running_on_demand",
                        "current_rentals_resident",
                        "current_rentals_on_demand",
                        "num_recent_reports",
                        "machine_maintenance",
                        "alloc_disk_space",
                        "timeout",
                    )

                    changed_fields = [
                        field for field in monitored_fields if getattr(old, field) != getattr(new, field)
                    ]

                    if changed_fields:
                        logger.info("Machine %s changed: %s", new.machine_id, changed_fields)
                        if config.debug:
                            before = {field: getattr(old, field) for field in changed_fields}
                            after = {field: getattr(new, field) for field in changed_fields}
                            logger.debug("Old: %s", json.dumps(before, indent=2))
                            logger.debug("New: %s", json.dumps(after, indent=2))

                        if any(
                            field in changed_fields
                            for field in (
                                "clients",
                                "gpu_occupancy",
                                "alloc_disk_space",
                                "current_rentals_running",
                                "current_rentals_running_on_demand",
                                "current_rentals_resident",
                                "current_rentals_on_demand",
                            )
                        ):
                            process_rental_changes(
                                old,
                                new,
                                paths=paths,
                                config=config,
                                logger=logger,
                                notifier=notifier,
                            )

                        if "error_description" in changed_fields:
                            snapshot = load_rental_snapshot(paths, new.machine_id)
                            minutes = error_ping_minutes
                            if new.error_description:
                                allow = True
                                last = snapshot.get("last_error_notified_at")
                                if last:
                                    try:
                                        last_dt = datetime.fromisoformat(last)
                                        allow = (datetime.now(timezone.utc) - last_dt).total_seconds() >= minutes * 60
                                    except Exception:
                                        allow = True
                                if allow and notifier:
                                    logger.error(
                                        "Machine %s error: %s",
                                        new.machine_id,
                                        new.error_description,
                                    )
                                    notifier.send_error(
                                        machine_id=new.machine_id,
                                        error=new.error_description,
                                    )
                                    snapshot["last_error_notified_at"] = datetime.now(timezone.utc).isoformat()
                                    save_rental_snapshot(paths, new.machine_id, snapshot)
                            else:
                                logger.info("Machine %s recovered from error.", new.machine_id)
                                if notifier:
                                    notifier.send_recovery(machine_id=new.machine_id)
                                if "last_error_notified_at" in snapshot:
                                    snapshot.pop("last_error_notified_at", None)
                                    save_rental_snapshot(paths, new.machine_id, snapshot)

                        if "timeout" in changed_fields:
                            snapshot = load_rental_snapshot(paths, new.machine_id)
                            minutes = error_ping_minutes
                            timeout_value = getattr(new, "timeout", 0) or 0
                            if timeout_value and int(timeout_value) > 0:
                                allow = True
                                last = snapshot.get("last_timeout_notified_at")
                                if last:
                                    try:
                                        last_dt = datetime.fromisoformat(last)
                                        allow = (datetime.now(timezone.utc) - last_dt).total_seconds() >= minutes * 60
                                    except Exception:
                                        allow = True
                                if allow and notifier:
                                    logger.error(
                                        "Machine %s timeout: %ss",
                                        new.machine_id,
                                        new.timeout,
                                    )
                                    notifier.send_error(
                                        machine_id=new.machine_id,
                                        error=f"Timeout: {new.timeout}s",
                                    )
                                    snapshot["last_timeout_notified_at"] = datetime.now(timezone.utc).isoformat()
                                    save_rental_snapshot(paths, new.machine_id, snapshot)
                            else:
                                logger.info(
                                    "Machine %s recovered from timeout.",
                                    new.machine_id,
                                )
                                if notifier:
                                    notifier.send_recovery(machine_id=new.machine_id)
                                if "last_timeout_notified_at" in snapshot:
                                    snapshot.pop("last_timeout_notified_at", None)
                                    save_rental_snapshot(paths, new.machine_id, snapshot)

                        save_machine_snapshot(paths, new)

            except Exception as exc:
                if config.debug:
                    logger.exception("Unexpected error in monitor loop: %s", exc)
                else:
                    logger.error(
                        "Unexpected error in monitor loop: %s: %s",
                        exc.__class__.__name__,
                        exc,
                    )
            logger.info("Sleeping for %s seconds.", config.check_frequency)
            time.sleep(config.check_frequency)
    except KeyboardInterrupt:
        logger.info("Received Ctrl+C, shutting down gracefully.")
        raise
