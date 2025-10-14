from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

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

_NUMBER_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _NUMBER_PATTERN.search(value)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
    return None


def _normalize_storage_size(value: float) -> float:
    normalized = float(value)
    # Vast may report storage in bytes/MB. Convert down until it is a practical GB scale.
    while normalized > 16384:
        normalized /= 1024.0
    return normalized


def _allocated_disk_gb(machine: VastMachine) -> Optional[float]:
    raw = getattr(machine, "alloc_disk_space", None)
    value = _to_float(raw)
    if value is None:
        return None
    normalized = _normalize_storage_size(value)
    return max(normalized, 0.0)


def _session_contracted_rate(session: object) -> Optional[float]:
    if isinstance(session, RentalSession):
        return _to_float(session.gpu_contracted_rate)
    if isinstance(session, dict):
        return _to_float(session.get("gpu_contracted_rate"))
    return None


def _session_gpu_type(session: object, fallback: Optional[str] = None) -> Optional[str]:
    if isinstance(session, RentalSession):
        gpu_type = session.gpu_type
    elif isinstance(session, dict):
        gpu_type = session.get("gpu_type")
    else:
        gpu_type = None
    return (gpu_type or fallback or "").strip() or None


def _contract_rate(session: object, fallback: float) -> float:
    contracted = _session_contracted_rate(session)
    if contracted is None or contracted <= 0:
        return fallback
    return float(contracted)


def _listing_rate_for_type(machine: VastMachine, rental_type: Optional[str]) -> Optional[float]:
    code = (rental_type or "").strip().upper()
    if code == "D":
        return _to_float(getattr(machine, "listed_gpu_cost", None))
    if code == "I":
        return _to_float(getattr(machine, "min_bid_price", None))
    if code == "R":
        return _to_float(getattr(machine, "bid_gpu_cost", None))
    return None


def _maybe_set_client_end(
    session: object,
    *,
    machine: VastMachine,
    rental_type: Optional[str],
    client_end_iso: Optional[str],
) -> None:
    if not client_end_iso:
        return
    existing_end: Optional[str]
    if isinstance(session, RentalSession):
        existing_end = session.client_end_date
    elif isinstance(session, dict):
        existing_end = session.get("client_end_date")
    else:
        existing_end = None
    if not existing_end:
        if isinstance(session, RentalSession):
            session.client_end_date = client_end_iso
        elif isinstance(session, dict):
            session["client_end_date"] = client_end_iso
        return
    contracted_rate = _session_contracted_rate(session)
    if contracted_rate is None:
        return
    listing_rate = _listing_rate_for_type(machine, rental_type or _session_gpu_type(session))
    if listing_rate is None:
        return
    if listing_rate <= contracted_rate + 1e-9:
        if isinstance(session, RentalSession):
            session.client_end_date = client_end_iso
        elif isinstance(session, dict):
            session["client_end_date"] = client_end_iso


def _extract_gpu_indices(source: object) -> list[int]:
    indices: list[int] = []
    if isinstance(source, list):
        for item in source:
            indices.extend(_extract_gpu_indices(item))
    elif isinstance(source, dict):
        for key, value in source.items():
            if not isinstance(key, str):
                continue
            lower = key.lower()
            if any(token in lower for token in ("gpu", "device", "idx", "index", "slot")):
                indices.extend(_extract_gpu_indices(value))
    else:
        numeric = _to_float(source)
        if numeric is None:
            return indices
        rounded = round(numeric)
        if abs(numeric - rounded) < 1e-6 and rounded >= 0:
            indices.append(int(rounded))
    return indices


def _client_gpu_indices(entry: object) -> Optional[tuple[int, ...]]:
    if not isinstance(entry, dict):
        return None
    candidates: list[list[int]] = []
    for key, value in entry.items():
        if not isinstance(key, str):
            continue
        lower = key.lower()
        if not any(token in lower for token in ("gpu", "device", "idx", "index", "slot")):
            continue
        if any(token in lower for token in ("util", "usage", "percent")):
            continue
        extracted = _extract_gpu_indices(value)
        if extracted:
            candidates.append(sorted(set(extracted)))
    if not candidates:
        return None
    candidates.sort(key=len, reverse=True)
    return tuple(candidates[0])


def _client_storage_gb(entry: object) -> Optional[float]:
    if not isinstance(entry, dict):
        return None
    candidates: list[float] = []
    for key, value in entry.items():
        if not isinstance(key, str):
            continue
        lower = key.lower()
        if not any(token in lower for token in ("stor", "disk", "volume")):
            continue
        if any(token in lower for token in ("price", "cost", "rate", "bandwidth", "util", "usage")):
            continue
        if isinstance(value, dict):
            nested = _client_storage_gb(value)
            if nested is not None:
                candidates.append(nested)
            continue
        if isinstance(value, list):
            for item in value:
                nested = _client_storage_gb(item)
                if nested is not None:
                    candidates.append(nested)
            continue
        numeric = _to_float(value)
        if numeric is None:
            continue
        candidates.append(_normalize_storage_size(numeric))
    positives = [val for val in candidates if val > 0.0]
    if positives:
        return max(positives)
    if candidates:
        return max(candidates)
    return None


def _timestamp_to_iso(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    try:
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _build_client_maps(machine: VastMachine) -> Tuple[Dict[tuple[int, ...], float], Dict[tuple[int, ...], str]]:
    mapping: Dict[tuple[int, ...], float] = {}
    contracts: Dict[tuple[int, ...], str] = {}
    clients = getattr(machine, "clients", None) or []
    for client in clients:
        key = _client_gpu_indices(client)
        if not key:
            continue
        storage = _client_storage_gb(client)
        if storage is None:
            storage = None
        if storage is not None:
            mapping[key] = storage
    return mapping, contracts


def _client_end_iso(machine: VastMachine) -> Optional[str]:
    raw = getattr(machine, "client_end_date", None)
    return _timestamp_to_iso(_to_float(raw))


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

    storage_map, contract_map = _build_client_maps(machine)
    client_end_iso = _client_end_iso(machine)

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
            key = tuple(sorted(chunk))
            storage_gb = storage_map.get(key, 0.0)
            contract_override = contract_map.get(key)
            session = RentalSession(
                client_id=sid,
                gpus=chunk,
                storage_gb=storage_gb,
                gpu_contracted_rate=rate,
                storage_contracted_rate=machine.listed_storage_cost,
            )
            session.gpu_type = rental_type
            session.open_gpu_segment(rate, len(chunk))
            session.open_storage_segment(machine.listed_storage_cost)
            _maybe_set_client_end(
                session,
                machine=machine,
                rental_type=rental_type,
                client_end_iso=contract_override or client_end_iso,
            )
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

    storage_map, contract_map = _build_client_maps(new)
    client_end_iso = _client_end_iso(new)

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

    old_disk = _allocated_disk_gb(old) or 0.0
    new_disk = _allocated_disk_gb(new) or 0.0

    handled_disk_releases: list[float] = []
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
                if storage_val:
                    handled_disk_releases.append(storage_val)
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
            session_data = snapshot["sessions"].get(running_match)
            if isinstance(session_data, dict):
                key = tuple(sorted(indices))
                storage_override = storage_map.get(key)
                if storage_override is not None:
                    session_data["storage_gb"] = storage_override
                _maybe_set_client_end(
                    session_data,
                    machine=new,
                    rental_type=session_data.get("gpu_type"),
                    client_end_iso=contract_map.get(key) or client_end_iso,
                )
            logger.debug(
                "Continuity detected: machine %s, session %s, gpus %s",
                new.machine_id,
                running_match,
                indices,
            )
            continue

        if matched_sid:
            session = RentalSession(**snapshot["sessions"][matched_sid])
            effective_rate = _contract_rate(session, rate)
            session.open_gpu_segment(effective_rate, len(indices))
            session.gpu_type = rental_type
            session.status = "running"
            key = tuple(sorted(indices))
            storage_override = storage_map.get(key)
            if storage_override is not None:
                session.storage_gb = storage_override
            _maybe_set_client_end(
                session,
                machine=new,
                rental_type=rental_type,
                client_end_iso=contract_map.get(key) or client_end_iso,
            )
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
                    rate=effective_rate,
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
                    effective_rate = _contract_rate(sess_resume, rate)
                    sess_resume.open_gpu_segment(effective_rate, len(indices))
                    sess_resume.gpu_type = rental_type
                    sess_resume.status = "running"
                    key = tuple(sorted(indices))
                    storage_override = storage_map.get(key)
                    if storage_override is not None:
                        sess_resume.storage_gb = storage_override
                    _maybe_set_client_end(
                        sess_resume,
                        machine=new,
                        rental_type=rental_type,
                        client_end_iso=contract_map.get(key) or client_end_iso,
                    )
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
                            rate=effective_rate,
                        )
                    continue
            sid = f"m{new.machine_id}-{seq:04d}"
            snapshot["next_session_seq"] = seq + 1
            key = tuple(sorted(indices))
            storage_from_client = storage_map.get(key)
            if storage_from_client is not None:
                storage_gb = storage_from_client
            elif disk_delta > 0:
                storage_gb = max(0.0, float(disk_delta))
            else:
                storage_gb = 0.0
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
            contract_rate = _contract_rate(session, rate)
            session.open_gpu_segment(contract_rate, len(indices))
            _maybe_set_client_end(
                session,
                machine=new,
                rental_type=rental_type,
                client_end_iso=contract_map.get(key) or client_end_iso,
            )
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
        if handled_disk_releases:
            total_released = sum(handled_disk_releases)
            accounted = any(abs(abs(disk_delta_only) - released) <= tol for released in handled_disk_releases)
            accounted = accounted or abs(abs(disk_delta_only) - total_released) <= tol
        else:
            accounted = False
        if accounted:
            handled_disk_releases.clear()
        elif disk_delta_only < -0.1:
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

    for sid, sdata in list(snapshot.get("sessions", {}).items()):
        if not isinstance(sdata, dict):
            continue
        status = sdata.get("status")
        if status == "running":
            gpus_list = sdata.get("gpus") or []
            if isinstance(gpus_list, list) and gpus_list:
                try:
                    key = tuple(sorted(int(idx) for idx in gpus_list))
                except Exception:
                    key = ()
                if key and key in storage_map:
                    sdata["storage_gb"] = storage_map[key]
        if status in {"running", "stored"}:
            key = ()
            if isinstance(sdata.get("gpus"), list):
                try:
                    key = tuple(sorted(int(idx) for idx in sdata["gpus"]))
                except Exception:
                    key = ()
            _maybe_set_client_end(
                sdata,
                machine=new,
                rental_type=sdata.get("gpu_type"),
                client_end_iso=contract_map.get(key) or client_end_iso,
            )

    snapshot["gpu_occupancy"] = new.gpu_occupancy
    snapshot["gpu_name"] = new.gpu_name
    snapshot["num_gpus"] = new.num_gpus
    save_rental_snapshot(paths, new.machine_id, snapshot)
