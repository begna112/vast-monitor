from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from notifications.services.base import BaseService
from notifications.utils import humanize_duration


class EmailService(BaseService):
    """Plain-text email formatter for notification events."""

    scheme = "email"

    def format_system_message(
        self, *, title: str, lines: Sequence[str]
    ) -> Tuple[str, str]:
        base_subject = title or "System Notification"
        subject = self._subject_with_timestamp(base_subject)
        body_lines = [base_subject, "=" * len(base_subject), ""]
        body_lines.extend(self._normalize_lines(lines))
        return subject, self._join(body_lines)

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
        base_subject = f"New rental on machine {machine_id}"
        subject = self._subject_with_timestamp(base_subject)
        body: List[str] = [base_subject, "=" * len(base_subject), ""]
        body.extend(
            self._session_block(session=session, rental_type=rental_type, rate=rate)
        )
        body.append("")
        body.append("Machine overview:")
        body.extend(self._machine_section(machine_id, snapshot, include_heading=True))
        return subject, self._join(body)

    def format_event_end(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
    ) -> Tuple[str, str]:
        base_subject = f"Rental ended on machine {machine_id}"
        subject = self._subject_with_timestamp(base_subject)
        body: List[str] = [base_subject, "=" * len(base_subject), ""]
        body.extend(self._session_block_end(session=session))
        body.append("")
        body.append("Machine overview:")
        body.extend(self._machine_section(machine_id, snapshot, include_heading=True))
        return subject, self._join(body)

    def format_startup_summary(
        self, *, items: Sequence[Dict[str, Any]]
    ) -> Tuple[str, str]:
        base_subject = "Startup summary"
        subject = self._subject_with_timestamp(base_subject)
        body: List[str] = [base_subject, "=" * len(base_subject), ""]
        for idx, item in enumerate(items, start=1):
            machine_id = item.get("machine_id")
            body.append(f"{idx}. Machine {machine_id}")
            body.extend(
                f"   {line}" for line in self._machine_section(machine_id, item.get("snapshot"), include_heading=False)
            )
            body.append("")
        return subject, self._join(body).rstrip()

    def format_error(
        self, *, machine_id: int, error: str, mention: Optional[str] = None
    ) -> Tuple[str, str]:
        base_subject = f"Machine {machine_id} error"
        subject = self._subject_with_timestamp(base_subject)
        body: List[str] = [base_subject, "=" * len(base_subject), "", error]
        if mention:
            body.append("")
            body.append(f"Mention: {mention}")
        return subject, self._join(body)

    def format_recovery(self, *, machine_id: int) -> Tuple[str, str]:
        base_subject = f"Machine {machine_id} recovered"
        subject = self._subject_with_timestamp(base_subject)
        body = [base_subject, "=" * len(base_subject), "", "Status: OK"]
        return subject, self._join(body)

    def format_event_pause(
        self, *, machine_id: int, session: Dict[str, Any], snapshot: Dict[str, Any]
    ) -> Tuple[str, str]:
        base_subject = f"Session paused on machine {machine_id}"
        subject = self._subject_with_timestamp(base_subject)
        body: List[str] = [base_subject, "=" * len(base_subject), ""]
        client_id = session.get("client_id")
        gpus = sorted(session.get("gpus", []))
        body.append(f"Session {client_id} paused; GPUs released: {gpus}")
        storage_gb = float(session.get("storage_gb", 0.0) or 0.0)
        if storage_gb:
            body.append(f"Storage retained: {storage_gb:.2f} GB")
        body.append("")
        body.append("Machine overview:")
        body.extend(self._machine_section(machine_id, snapshot, include_heading=True))
        return subject, self._join(body)

    def format_event_resume(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        rate: float,
    ) -> Tuple[str, str]:
        base_subject = f"Session resumed on machine {machine_id}"
        subject = self._subject_with_timestamp(base_subject)
        body: List[str] = [base_subject, "=" * len(base_subject), ""]
        body.extend(
            self._session_block(
                session=session, rental_type=session.get("gpu_type", "?"), rate=rate
            )
        )
        body.append("")
        body.append("Machine overview:")
        body.extend(self._machine_section(machine_id, snapshot, include_heading=True))
        return subject, self._join(body)

    # Helper utilities
    def _subject_with_timestamp(self, base: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"{base} [{ts}]"

    def _normalize_lines(self, lines: Sequence[str]) -> List[str]:
        normalized: List[str] = []
        for line in lines:
            if line is None:
                continue
            text = str(line)
            if not text:
                normalized.append("")
                continue
            text = self._replace_discord_timestamps(text)
            if text.strip():
                normalized.append(text.strip())
            else:
                normalized.append("")
        return self._collapse_empty_trailing(normalized)

    def _replace_discord_timestamps(self, text: str) -> str:
        pattern = re.compile(r"<t:(\d+):([a-zA-Z])>")
        now = datetime.now(timezone.utc)

        def _render(match: re.Match[str]) -> str:
            epoch = int(match.group(1))
            style = match.group(2)
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            if style.lower() == "r":
                delta = (now - dt).total_seconds()
                human = humanize_duration(abs(delta))
                if delta >= 0:
                    return f"{human} ago"
                return f"in {human}"
            return dt.isoformat()

        replaced = pattern.sub(_render, text)
        if "Discord:" in replaced:
            replaced = replaced.replace("Discord:", "Timestamp:")
        return replaced

    def _format_timestamp(self, value: Optional[str]) -> str:
        if not value:
            return ""
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return value
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = delta.total_seconds()
        suffix = "ago" if seconds >= 0 else "from now"
        rel = humanize_duration(abs(seconds))
        return f"{dt.isoformat()} ({rel} {suffix})"

    def _collapse_empty_trailing(self, lines: List[str]) -> List[str]:
        while lines and lines[-1] == "":
            lines.pop()
        return lines

    def _join(self, parts: List[str]) -> str:
        body = "\n".join(parts)
        return f"<pre>{body}</pre>"


    def _machine_section(
        self,
        machine_id: int,
        snapshot: Optional[Dict[str, Any]],
        *,
        include_heading: bool = True,
    ) -> List[str]:
        snapshot = snapshot or {}
        sessions = snapshot.get("sessions", {}) if isinstance(snapshot, dict) else {}
        occupancy = (snapshot.get("gpu_occupancy") or "").split()
        used = sum(1 for tok in occupancy if tok and tok != "x")
        total = len(occupancy) if occupancy else snapshot.get("num_gpus") or 0
        pct = int(round((used / total) * 100)) if total else 0
        gpu_total_hr = 0.0
        disk_total_hr = 0.0
        for sess in sessions.values():
            gh, dh, _ = self._session_hourly(sess)
            gpu_total_hr += gh
            disk_total_hr += dh

        lines: List[str] = []
        if include_heading:
            lines.append(f"Machine {machine_id}")
        gpu_name = ""
        if isinstance(snapshot, dict):
            gpu_name = snapshot.get("gpu_name") or ""
        gpu_label = f" {gpu_name}" if gpu_name else ""
        lines.append(
            f"Occupancy: {used}/{total}{gpu_label} GPUs ({pct}%)"
        )
        lines.append(
            f"Total est hourly: {gpu_total_hr:.4f}$ (GPUs) + {disk_total_hr:.4f}$ (disk) = {(gpu_total_hr + disk_total_hr):.4f}$"
        )
        lines.append(f"Active sessions: {len(sessions)}")
        if not sessions:
            lines.append("- No active sessions")
            return lines

        for sid, sess in sessions.items():
            gpus = sorted(sess.get("gpus", []))
            gh, dh, th = self._session_hourly(sess)
            gpu_type = sess.get("gpu_type") or sess.get("type") or "?"
            current_rate = self._current_gpu_rate(sess)
            storage_gb = float(sess.get("storage_gb", 0.0) or 0.0)
            storage_rate = self._current_storage_rate(sess)
            gpu_total, storage_total, total_earned = self._session_totals(sess)
            start_line = self._format_timestamp(sess.get("start_time"))

            lines.append(f"- {sid}:")
            if gpus:
                lines.append(
                    f"  - GPUs: x{len(gpus)} {gpus} {gpu_type} @ {current_rate:.4f}$/GPU/hr"
                )
            if storage_gb:
                lines.append(
                    f"  - Storage: {storage_gb:.2f} GB @ {storage_rate:.4f}$/GB/mo"
                )
            lines.append(
                f"  - Est hourly: {gh:.4f}$ (GPUs) + {dh:.4f}$ (disk) = {th:.4f}$"
            )
            lines.append(
                f"  - Earnings: {gpu_total:.4f}$ (GPUs) + {storage_total:.4f}$ (disk) = {total_earned:.4f}$"
            )
            contract_line = self._format_timestamp(sess.get("client_end_date"))
            if start_line:
                lines.append(f"  - Start: {start_line}")
            if contract_line:
                lines.append(f"  - Contract end: {contract_line}")
        return lines

    def _session_block(
        self, *, session: Dict[str, Any], rental_type: str, rate: float
    ) -> List[str]:
        sid = session.get("client_id")
        gpus = sorted(session.get("gpus", []))
        gcount = len(gpus)
        gpu_hourly = rate * gcount
        storage_gb = float(session.get("storage_gb", 0.0) or 0.0)
        storage_rate = self._current_storage_rate(session)
        storage_hourly = (storage_rate * storage_gb) / 730.0 if storage_gb else 0.0
        total_hourly = gpu_hourly + storage_hourly
        start_line = self._format_timestamp(session.get("start_time"))

        lines = [
            f"- {sid}:",
            f"  - {rental_type} @ ${rate:.4f}/gpu (est hourly {gpu_hourly:.4f}$ (GPUs) + {storage_hourly:.4f}$ (disk) = {total_hourly:.4f}$)",
            f"  - x{gcount} GPUs allocated: {gpus}",
        ]
        if storage_gb:
            lines.append(
                f"  - Storage: {storage_gb:.2f} GB @ {storage_rate:.4f}$/GB/mo"
            )
        if start_line:
            lines.append(f"  - Start: {start_line}")
        contract_line = self._format_timestamp(session.get("client_end_date"))
        if contract_line:
            lines.append(f"  - Contract end: {contract_line}")
        return lines

    def _session_block_end(self, *, session: Dict[str, Any]) -> List[str]:
        sid = session.get("client_id")
        gpus = sorted(session.get("gpus", []))
        duration_secs = float(session.get("rental_duration") or 0.0)
        duration = humanize_duration(duration_secs)
        gpu_total = float(session.get("earned_gpu", 0.0) or 0.0)
        storage_total = float(session.get("earned_storage", 0.0) or 0.0)
        total_earned = float(session.get("estimated_earnings") or (gpu_total + storage_total))
        start_line = self._format_timestamp(session.get("start_time"))
        end_line = self._format_timestamp(session.get("end_time"))

        lines = [
            f"- {sid}:",
            f"  - x{len(gpus)} GPUs released: {gpus}",
            f"  - Duration: {duration}",
            f"  - Total earned: {gpu_total:.4f}$ (GPUs) + {storage_total:.4f}$ (disk) = {total_earned:.4f}$",
        ]
        if start_line:
            lines.append(f"  - Start: {start_line}")
        if end_line:
            lines.append(f"  - End: {end_line}")
        return lines

    def _current_gpu_rate(self, session: Dict[str, Any]) -> float:
        for seg in reversed(session.get("gpu_segments", []) or []):
            if seg.get("end") is None:
                return float(seg.get("rate", 0.0) or 0.0)
        return 0.0

    def _current_storage_rate(self, session: Dict[str, Any]) -> float:
        for seg in reversed(session.get("storage_segments", []) or []):
            if seg.get("end") is None:
                return float(seg.get("rate_per_gb_month", 0.0) or 0.0)
        return 0.0

    def _session_hourly(self, session: Dict[str, Any]) -> Tuple[float, float, float]:
        gpus = session.get("gpus", []) or []
        rate = self._current_gpu_rate(session)
        gpu_hr = rate * len(gpus) if gpus else 0.0
        storage_gb = float(session.get("storage_gb", 0.0) or 0.0)
        storage_rate = self._current_storage_rate(session)
        disk_hr = (storage_rate * storage_gb) / 730.0 if storage_gb else 0.0
        return gpu_hr, disk_hr, gpu_hr + disk_hr

    def _session_totals(self, session: Dict[str, Any]) -> Tuple[float, float, float]:
        now_ts = datetime.now(timezone.utc)
        gpu_total = 0.0
        for seg in session.get("gpu_segments", []) or []:
            try:
                start = datetime.fromisoformat(seg.get("start"))
                end_val = seg.get("end")
                end = datetime.fromisoformat(end_val) if end_val else now_ts
                secs = max(0.0, (end - start).total_seconds())
                rate = float(seg.get("rate", 0.0) or 0.0)
                count = int(seg.get("gpu_count", 0) or 0)
                gpu_total += rate * count * (secs / 3600.0)
            except Exception:
                continue
        storage_total = 0.0
        storage_gb = float(session.get("storage_gb", 0.0) or 0.0)
        for seg in session.get("storage_segments", []) or []:
            try:
                start = datetime.fromisoformat(seg.get("start"))
                end_val = seg.get("end")
                end = datetime.fromisoformat(end_val) if end_val else now_ts
                secs = max(0.0, (end - start).total_seconds())
                rate = float(seg.get("rate_per_gb_month", 0.0) or 0.0)
                storage_total += (rate * storage_gb) * (secs / (730.0 * 3600.0))
            except Exception:
                continue
        return gpu_total, storage_total, gpu_total + storage_total
