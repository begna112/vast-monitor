from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from Classes.rental_session import RentalSession
from Classes.vast_machine import VastMachine


@dataclass
class StatePaths:
    base_dir: Path
    snapshots_dir: Path
    rental_snapshot_path: Path
    rental_logs_dir: Path

    @classmethod
    def for_base_dir(cls, base_dir: Path) -> "StatePaths":
        base = base_dir.expanduser().resolve()
        return cls(
            base_dir=base,
            snapshots_dir=base / "machine_snapshots",
            rental_snapshot_path=base / "rental_snapshot.json",
            rental_logs_dir=base / "rental_logs",
        )


def ensure_state_dirs(paths: StatePaths) -> None:
    paths.snapshots_dir.mkdir(parents=True, exist_ok=True)
    paths.rental_logs_dir.mkdir(parents=True, exist_ok=True)


def save_machine_snapshot(paths: StatePaths, machine: VastMachine) -> None:
    path = paths.snapshots_dir / f"{machine.machine_id}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(machine.model_dump(), fh, indent=2)


def load_machine_snapshot(paths: StatePaths, machine: VastMachine) -> VastMachine:
    path = paths.snapshots_dir / f"{machine.machine_id}.json"
    with path.open("r", encoding="utf-8") as fh:
        return VastMachine(**json.load(fh))


def load_all_rental_snapshots(paths: StatePaths) -> Dict[str, Dict]:
    if not paths.rental_snapshot_path.exists():
        return {}
    with paths.rental_snapshot_path.open("r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError:
            data = {}
    if isinstance(data, dict):
        return data
    return {}


def load_rental_snapshot(paths: StatePaths, machine_id: int) -> Dict:
    data = load_all_rental_snapshots(paths)
    return data.get(
        str(machine_id),
        {"gpus": {}, "gpu_occupancy": "", "sessions": {}, "next_session_seq": 1},
    )


def save_rental_snapshot(paths: StatePaths, machine_id: int, snapshot: Dict) -> None:
    data = load_all_rental_snapshots(paths)
    data[str(machine_id)] = snapshot
    paths.rental_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.rental_snapshot_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def save_rental_log(paths: StatePaths, session: RentalSession) -> None:
    paths.rental_logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{timestamp}_client_{session.client_id}.json"
    dest = paths.rental_logs_dir / filename
    with dest.open("w", encoding="utf-8") as fh:
        json.dump(session.model_dump(), fh, indent=2)
