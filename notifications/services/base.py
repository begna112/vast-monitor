from __future__ import annotations
from typing import Tuple, Sequence, Dict, Any, List, Optional


class BaseService:
    scheme: str = "default"

    def format_system_message(self, *, title: str, lines: Sequence[str]) -> Tuple[str, str]:
        raise NotImplementedError

    def format_event_start(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        rental_type: str,
        rate: float,
        indices: Sequence[int],
    ) -> Tuple[str, str]:
        raise NotImplementedError

    def format_event_end(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
    ) -> Tuple[str, str]:
        raise NotImplementedError

    def format_startup_summary(
        self, *, items: Sequence[Dict[str, Any]]
    ) -> Tuple[str, str]:
        """items: sequence of dicts with keys 'machine_id', 'num_gpus', 'gpu_occupancy', 'snapshot'"""
        raise NotImplementedError

    def format_error(
        self, *, machine_id: int, error: str, mention: Optional[str] = None
    ) -> Tuple[str, str]:
        raise NotImplementedError

    def format_recovery(self, *, machine_id: int) -> Tuple[str, str]:
        raise NotImplementedError

    def format_event_pause(
        self, *, machine_id: int, session: Dict[str, Any], snapshot: Dict[str, Any]
    ) -> Tuple[str, str]:
        raise NotImplementedError

    def format_event_resume(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        rate: float,
    ) -> Tuple[str, str]:
        raise NotImplementedError
