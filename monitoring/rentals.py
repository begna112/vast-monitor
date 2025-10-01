from __future__ import annotations

import logging
from typing import Dict, Optional

from Classes.app_config import AppConfig
from Classes.rental_session import RentalSession
from Classes.vast_machine import VastMachine
from notifications.dispatcher import NotificationManager

from monitoring.state import (
    StatePaths,
    load_rental_snapshot,
    save_rental_snapshot,
    save_rental_log,
)


def seed_sessions_for_current_occupancy(
    machine: VastMachine,
    *,
    paths: StatePaths,
    logger: logging.Logger,
) -> Dict:
    """Create placeholder sessions for occupied GPUs that are not yet tracked."""
    snapshot = load_rental_snapshot(paths, machine.machine_id)
    snapshot.setdefault("gpus", {})
    snapshot.setdefault("sessions", {})
    snapshot.setdefault("next_session_seq", 1)

    def _as_int(value: object) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    current_running = _as_int(getattr(machine, "current_rentals_running", 0))
    current_running_on_demand = _as_int(
        getattr(machine, "current_rentals_running_on_demand", 0)
    )
    current_resident = _as_int(getattr(machine, "current_rentals_resident", 0))
    current_resident_on_demand = _as_int(
        getattr(machine, "current_rentals_on_demand", 0)
    )

    snapshot["current_rentals_running"] = current_running
    snapshot["current_rentals_running_on_demand"] = current_running_on_demand
    snapshot["current_rentals_resident"] = current_resident
    snapshot["current_rentals_on_demand"] = current_resident_on_demand
    snapshot["gpu_name"] = machine.gpu_name

    occ = machine.gpu_occupancy.split()
    groups: Dict[tuple[str, float], list[int]] = {}
    for index, token in enumerate(occ):
        token = token.strip()
        if not token or token == "x":
            continue
        key = str(index)
        if key in snapshot["gpus"]:
            continue
        if token == "D":
            rate = machine.listed_gpu_cost
        elif token == "I":
            rate = machine.min_bid_price
        elif token == "R":
            rate = machine.bid_gpu_cost or 0.0
        else:
            rate = 0.0
        groups.setdefault((token, float(rate or 0.0)), []).append(index)

    remaining_on_demand = current_running_on_demand
    remaining_other = max(current_running - current_running_on_demand, 0)

    def split_indices(indices: list[int], session_count: int) -> list[list[int]]:
        if not indices:
            return []
        session_count = max(1, min(session_count, len(indices)))
        chunks: list[list[int]] = []
        remaining = len(indices)
        cursor = 0
        for i in range(session_count):
            sessions_left = session_count - i
            take = max(1, remaining - (sessions_left - 1))
            chunk = indices[cursor : cursor + take]
            chunks.append(chunk)
            cursor += take
            remaining -= take
        return chunks

    for (rental_type, rate), indices in sorted(groups.items()):
        if rental_type == "D":
            desired = min(len(indices), remaining_on_demand) if remaining_on_demand else 0
            remaining_on_demand = max(remaining_on_demand - desired, 0)
        else:
            desired = min(len(indices), remaining_other) if remaining_other else 0
            remaining_other = max(remaining_other - desired, 0)

        session_chunks = split_indices(indices, desired)
        for chunk in session_chunks:
            if not chunk:
                continue
            seq = snapshot.get("next_session_seq", 1)
            sid = f"m{machine.machine_id}-{seq:04d}"
            snapshot["next_session_seq"] = seq + 1
            session = RentalSession(
                client_id=sid,
                gpus=chunk,
                gpu_contracted_rate=rate,
                storage_contracted_rate=machine.listed_storage_cost,
            )
            session.gpu_type = rental_type
            session.open_gpu_segment(rate, len(chunk))
            session.open_storage_segment(machine.listed_storage_cost)
            snapshot["sessions"][sid] = session.model_dump()
            for idx in chunk:
                snapshot["gpus"][str(idx)] = sid
            logger.info(
                "Detected ongoing rental at startup: machine %s, session %s, type %s, rate %s, gpus %s",
                machine.machine_id,
                sid,
                rental_type,
                rate,
                chunk,
            )

    snapshot["gpu_occupancy"] = machine.gpu_occupancy
    snapshot["gpu_name"] = machine.gpu_name
    snapshot["num_gpus"] = machine.num_gpus
    save_rental_snapshot(paths, machine.machine_id, snapshot)
    return snapshot


def process_rental_changes(
    old: VastMachine,
    new: VastMachine,
    *,
    paths: StatePaths,
    config: AppConfig,
    logger: logging.Logger,
    notifier: Optional[NotificationManager],
) -> None:
    snapshot = load_rental_snapshot(paths, new.machine_id)
    snapshot.setdefault("gpus", {})
    snapshot.setdefault("sessions", {})
    snapshot.setdefault("next_session_seq", 1)
    snapshot["gpu_name"] = new.gpu_name
    snapshot.pop("clients", None)

    def _as_int(value: object) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    old_resident = _as_int(old.current_rentals_resident)
    new_resident = _as_int(new.current_rentals_resident)
    old_resident_on_demand = _as_int(old.current_rentals_on_demand)
    new_resident_on_demand = _as_int(new.current_rentals_on_demand)
    old_running = _as_int(old.current_rentals_running)
    new_running = _as_int(new.current_rentals_running)
    old_running_on_demand = _as_int(old.current_rentals_running_on_demand)
    new_running_on_demand = _as_int(new.current_rentals_running_on_demand)

    # Track how many sessions newly enter the stored state this cycle
    old_stored_on_demand = max(old_resident_on_demand - old_running_on_demand, 0)
    new_stored_on_demand = max(new_resident_on_demand - new_running_on_demand, 0)
    pause_budget_on_demand = max(new_stored_on_demand - old_stored_on_demand, 0)

    old_interruptible_total = max(old_resident - old_resident_on_demand, 0)
    new_interruptible_total = max(new_resident - new_resident_on_demand, 0)
    old_running_interruptible = max(old_running - old_running_on_demand, 0)
    new_running_interruptible = max(new_running - new_running_on_demand, 0)
    old_stored_interruptible = max(old_interruptible_total - old_running_interruptible, 0)
    new_stored_interruptible = max(new_interruptible_total - new_running_interruptible, 0)
    pause_budget_interruptible = max(new_stored_interruptible - old_stored_interruptible, 0)
    snapshot["current_rentals_running"] = new_running
    snapshot["current_rentals_running_on_demand"] = new_running_on_demand
    snapshot["current_rentals_resident"] = new_resident
    snapshot["current_rentals_on_demand"] = new_resident_on_demand


    old_occ = snapshot.get("gpu_occupancy", ("x " * new.num_gpus)).split()
    new_occ = new.gpu_occupancy.split()
    if len(old_occ) < new.num_gpus:
        old_occ = old_occ + ["x"] * (new.num_gpus - len(old_occ))

    def occupied(token: str) -> bool:
        return bool(token) and token != "x"

    ended_indices = [
        idx
        for idx, (o, n) in enumerate(zip(old_occ, new_occ))
        if (occupied(o) and not occupied(n)) or (occupied(o) and occupied(n) and o != n)
    ]
    started_indices = [
        idx
        for idx, (o, n) in enumerate(zip(old_occ, new_occ))
        if (not occupied(o) and occupied(n)) or (occupied(o) and occupied(n) and o != n)
    ]

    try:
        old_disk = float(old.alloc_disk_space or 0.0)
    except Exception:
        old_disk = 0.0
    try:
        new_disk = float(new.alloc_disk_space or 0.0)
    except Exception:
        new_disk = 0.0

    ended_map: Dict[str, list[int]] = {}
    for idx in ended_indices:
        sid = snapshot["gpus"].pop(str(idx), None)
        if not sid:
            continue
        ended_map.setdefault(sid, []).append(idx)

    for sid, freed in ended_map.items():
        session_data = snapshot["sessions"].get(sid)
        if not session_data:
            continue
        session = RentalSession(**session_data)
        prev_gpus = list(session.gpus)
        remaining = [gpu for gpu in prev_gpus if gpu not in freed]
        if remaining:
            session.close_gpu_segment()
            session.gpus = remaining
            rental_type = new_occ[remaining[0]] if remaining else "?"
            if rental_type == "D":
                current_rate = new.listed_gpu_cost
            elif rental_type == "I":
                current_rate = new.min_bid_price
            elif rental_type == "R":
                current_rate = new.bid_gpu_cost or 0.0
            else:
                current_rate = 0.0
            effective_rate = min(current_rate, session.gpu_contracted_rate or current_rate)
            session.open_gpu_segment(effective_rate, len(remaining))
            snapshot["sessions"][sid] = session.model_dump()
            logger.debug(
                "GPUs %s released: machine %s, session %s, remaining %s (was %s)",
                freed,
                new.machine_id,
                sid,
                remaining,
                prev_gpus,
            )
        else:
            disk_delta = new_disk - old_disk
            tol = 1.0
            storage_val = float(session.storage_gb or 0.0)
            is_on_demand = session.gpu_type == "D"
            budget_type: Optional[str] = None
            if is_on_demand and pause_budget_on_demand > 0:
                budget_type = "on_demand"
            elif not is_on_demand and pause_budget_interruptible > 0:
                budget_type = "interruptible"

            should_pause = budget_type is not None and abs(disk_delta) < tol
            standard_end = abs(disk_delta + storage_val) < tol

            if should_pause:
                if budget_type == "on_demand":
                    pause_budget_on_demand -= 1
                else:
                    pause_budget_interruptible -= 1
                session.close_gpu_segment()
                session.status = "stored"
                snapshot["sessions"][sid] = session.model_dump()
                logger.info(
                    "Session paused: machine %s, session %s, GPUs released %s",
                    new.machine_id,
                    sid,
                    prev_gpus,
                )
                snapshot["gpu_occupancy"] = new.gpu_occupancy
                snapshot["gpu_name"] = new.gpu_name
                snapshot["num_gpus"] = new.num_gpus
                if notifier:
                    notifier.send_event_pause(
                        machine_id=new.machine_id,
                        session=session.model_dump(),
                        snapshot=snapshot,
                    )
            else:
                if not standard_end:
                    logger.warning(
                        "Ambiguous disk change %.2f GB for session %s; treating as ended.",
                        disk_delta,
                        sid,
                    )
                session.finalize_end()
                dur, gpu_total, storage_total, total = session.totals(session.end_time)
                sdict = session.model_dump()
                sdict["earned_gpu"] = round(gpu_total, 6)
                sdict["earned_storage"] = round(storage_total, 6)
                save_rental_log(paths, session)
                snapshot["sessions"].pop(sid, None)
                logger.info("Rental ended: machine %s, session %s", new.machine_id, sid)
                snapshot["gpu_occupancy"] = new.gpu_occupancy
                snapshot["gpu_name"] = new.gpu_name
                snapshot["num_gpus"] = new.num_gpus
                if notifier:
                    notifier.send_event_end(
                        machine_id=new.machine_id,
                        session=sdict,
                        snapshot=snapshot,
                    )

    group_map: Dict[tuple, list[int]] = {}
    for idx in started_indices:
        rental_type = new_occ[idx] if idx < len(new_occ) else "?"
        if rental_type == "D":
            rate = new.listed_gpu_cost
        elif rental_type == "I":
            rate = new.min_bid_price
        elif rental_type == "R":
            rate = new.bid_gpu_cost or 0.0
        else:
            rate = 0.0
        group_map.setdefault((rental_type, rate), []).append(idx)

    for (rental_type, rate), indices in group_map.items():
        seq = snapshot.get("next_session_seq", 1)
        matched_sid = None
        for sid0, sdata in snapshot["sessions"].items():
            try:
                if sdata.get("status") == "stored" and sorted(sdata.get("gpus", [])) == sorted(indices):
                    matched_sid = sid0
                    break
            except Exception:
                continue

        running_match = None
        for sid0, sdata in snapshot["sessions"].items():
            try:
                if sdata.get("status") == "running" and sorted(sdata.get("gpus", [])) == sorted(indices):
                    running_match = sid0
                    break
            except Exception:
                continue

        if running_match:
            for idx in indices:
                snapshot["gpus"][str(idx)] = running_match
            logger.debug(
                "Continuity detected: machine %s, session %s, gpus %s",
                new.machine_id,
                running_match,
                indices,
            )
            continue

        if matched_sid:
            session = RentalSession(**snapshot["sessions"][matched_sid])
            effective_rate = min(rate, session.gpu_contracted_rate or rate)
            session.open_gpu_segment(effective_rate, len(indices))
            session.gpu_type = rental_type
            session.status = "running"
            snapshot["sessions"][matched_sid] = session.model_dump()
            for idx in indices:
                snapshot["gpus"][str(idx)] = matched_sid
            logger.info(
                "Session resumed: machine %s, session %s, gpus %s",
                new.machine_id,
                matched_sid,
                indices,
            )
            snapshot["gpu_occupancy"] = new.gpu_occupancy
            snapshot["gpu_name"] = new.gpu_name
            snapshot["num_gpus"] = new.num_gpus
            if notifier:
                notifier.send_event_resume(
                    machine_id=new.machine_id,
                    session=session.model_dump(),
                    snapshot=snapshot,
                    rate=rate,
                )
        else:
            disk_delta = new_disk - old_disk
            tol = 1.0
            if abs(disk_delta) < tol:
                stored_list = [
                    sid0
                    for sid0, sdata0 in snapshot["sessions"].items()
                    if isinstance(sdata0, dict) and sdata0.get("status") == "stored"
                ]
                if len(stored_list) == 1:
                    sid_resume = stored_list[0]
                    sess_resume = RentalSession(**snapshot["sessions"][sid_resume])
                    sess_resume.gpus = indices
                    effective_rate = min(rate, sess_resume.gpu_contracted_rate or rate)
                    sess_resume.open_gpu_segment(effective_rate, len(indices))
                    sess_resume.gpu_type = rental_type
                    sess_resume.status = "running"
                    snapshot["sessions"][sid_resume] = sess_resume.model_dump()
                    for idx in indices:
                        snapshot["gpus"][str(idx)] = sid_resume
                    logger.info(
                        "Session resumed (disk-continuity): machine %s, session %s, gpus %s",
                        new.machine_id,
                        sid_resume,
                        indices,
                    )
                    snapshot["gpu_occupancy"] = new.gpu_occupancy
                    snapshot["gpu_name"] = new.gpu_name
                    snapshot["num_gpus"] = new.num_gpus
                    if notifier:
                        notifier.send_event_resume(
                            machine_id=new.machine_id,
                            session=sess_resume.model_dump(),
                            snapshot=snapshot,
                            rate=rate,
                        )
                    continue
            sid = f"m{new.machine_id}-{seq:04d}"
            snapshot["next_session_seq"] = seq + 1
            storage_gb = max(0.0, float(disk_delta)) if disk_delta > 0 else 0.0
            session = RentalSession(
                client_id=sid,
                status="running",
                gpus=indices,
                storage_gb=storage_gb,
                gpu_contracted_rate=rate,
                storage_contracted_rate=new.listed_storage_cost,
            )
            session.gpu_type = rental_type
            session.open_storage_segment(
                min(new.listed_storage_cost, session.storage_contracted_rate)
            )
            session.open_gpu_segment(min(rate, session.gpu_contracted_rate), len(indices))
            snapshot["sessions"][sid] = session.model_dump()
            for idx in indices:
                snapshot["gpus"][str(idx)] = sid
            logger.info(
                "New rental: machine %s, session %s, type %s, rate %s, gpus %s",
                new.machine_id,
                sid,
                rental_type,
                rate,
                indices,
            )
            snapshot["gpu_occupancy"] = new.gpu_occupancy
            snapshot["gpu_name"] = new.gpu_name
            snapshot["num_gpus"] = new.num_gpus
            if notifier:
                notifier.send_event_start(
                    machine_id=new.machine_id,
                    session=session.model_dump(),
                    snapshot=snapshot,
                    rental_type=rental_type,
                    rate=rate,
                    indices=indices,
                )

    try:
        disk_delta_only = new_disk - old_disk
        tol = 1.0
        if disk_delta_only < -0.1:
            target_drop = abs(disk_delta_only)
            stored_sessions = [
                (sid, sdata)
                for sid, sdata in snapshot.get("sessions", {}).items()
                if isinstance(sdata, dict) and sdata.get("status") == "stored"
            ]
            if stored_sessions:
                best_sid = None
                best_diff = None
                best_session = None
                for sid, sdata in stored_sessions:
                    storage_gb = float(sdata.get("storage_gb", 0.0) or 0.0)
                    diff = abs(storage_gb - target_drop)
                    if best_diff is None or diff < best_diff:
                        best_sid, best_diff, best_session = sid, diff, sdata
                if (
                    best_sid is not None
                    and best_diff is not None
                    and best_diff <= tol
                    and best_session is not None
                ):
                    session = RentalSession(**best_session)
                    session.finalize_end()
                    dur, gpu_total, storage_total, total = session.totals(session.end_time)
                    sdict = session.model_dump()
                    sdict["earned_gpu"] = round(gpu_total, 6)
                    sdict["earned_storage"] = round(storage_total, 6)
                    save_rental_log(paths, session)
                    snapshot["sessions"].pop(best_sid, None)
                    logger.info(
                        "Rental ended (disk-only): machine %s, session %s",
                        new.machine_id,
                        best_sid,
                    )
                    snapshot["gpu_occupancy"] = new.gpu_occupancy
                    snapshot["gpu_name"] = new.gpu_name
                    snapshot["num_gpus"] = new.num_gpus
                    if notifier:
                        notifier.send_event_end(
                            machine_id=new.machine_id,
                            session=sdict,
                            snapshot=snapshot,
                        )
                else:
                    logger.warning(
                        "Disk-only drop %.2f GB did not match stored session within tolerance.",
                        target_drop,
                    )
    except Exception as exc:
        if config.debug:
            logger.exception(f"Disk-only termination handling failed: {exc}")
        else:
            logger.error(
                "Disk-only termination handling failed: %s: %s",
                exc.__class__.__name__,
                exc,
            )

    snapshot["gpu_occupancy"] = new.gpu_occupancy
    snapshot["gpu_name"] = new.gpu_name
    snapshot["num_gpus"] = new.num_gpus
    save_rental_snapshot(paths, new.machine_id, snapshot)
