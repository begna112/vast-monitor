from __future__ import annotations
from typing import Tuple, Sequence, Dict, Any, List, Optional
from datetime import datetime, timezone
from notifications.services.base import BaseService
from notifications.utils import HR, humanize_duration


class DefaultService(BaseService):
    scheme = "default"

    def _h2(self, title: str) -> str:
        return f"## {title}"

    def _h3(self, title: str) -> str:
        return f"### {title}"

    def format_system_message(
        self, *, title: str, lines: Sequence[str]
    ) -> Tuple[str, str]:
        header = self._h2(title)
        body = "\n".join([HR, header, "\n".join(lines)])
        return title, body

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
        header = self._h2("New Rental")
        lines: List[str] = [f"Machine {machine_id}"]
        lines.extend(
            self._session_block(session=session, rental_type=rental_type, rate=rate)
        )
        item = {
            "machine_id": machine_id,
            "num_gpus": snapshot.get("num_gpus", 0),
            "gpu_occupancy": snapshot.get("gpu_occupancy", ""),
            "snapshot": snapshot,
        }
        section = self._machine_section(machine_id, item)
        body = "\n".join([HR, header, "\n".join(lines), section])
        return "New Rental", body

    def format_event_end(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
    ) -> Tuple[str, str]:
        header = self._h2("Rental Ended")
        lines: List[str] = [f"Machine {machine_id}"]
        lines.extend(self._session_block_end(session=session))
        item = {
            "machine_id": machine_id,
            "num_gpus": snapshot.get("num_gpus", 0),
            "gpu_occupancy": snapshot.get("gpu_occupancy", ""),
            "snapshot": snapshot,
        }
        section = self._machine_section(machine_id, item)
        body = "\n".join([HR, header, "\n".join(lines), section])
        return "Rental Ended", body

    def format_event_pause(
        self, *, machine_id: int, session: Dict[str, Any], snapshot: Dict[str, Any]
    ) -> Tuple[str, str]:
        header = self._h2("Session Paused")
        lines: List[str] = [f"Machine {machine_id}"]
        sid = session.get("client_id")
        gpus = sorted(session.get("gpus", []))
        storage_gb = session.get("storage_gb", 0.0)
        lines.append(f"- {sid}:")
        lines.append(f"  - x{len(gpus)} GPUs released: {gpus}")
        lines.append(f"  - Storage: {storage_gb:.2f} GB continues")
        item = {
            "machine_id": machine_id,
            "num_gpus": snapshot.get("num_gpus", 0),
            "gpu_occupancy": snapshot.get("gpu_occupancy", ""),
            "snapshot": snapshot,
        }
        section = self._machine_section(machine_id, item)
        body = "\n".join([HR, header, "\n".join(lines), section])
        return "Session Paused", body

    def format_event_resume(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        rate: float,
    ) -> Tuple[str, str]:
        header = self._h2("Session Resumed")
        lines: List[str] = [f"Machine {machine_id}"]
        sid = session.get("client_id")
        gpus = sorted(session.get("gpus", []))
        lines.append(f"- {sid}:")
        lines.append(f"  - x{len(gpus)} GPUs allocated: {gpus}")
        lines.append(f"  - GPU rate: ${rate:.4f}/gpu/hr")
        item = {
            "machine_id": machine_id,
            "num_gpus": snapshot.get("num_gpus", 0),
            "gpu_occupancy": snapshot.get("gpu_occupancy", ""),
            "snapshot": snapshot,
        }
        section = self._machine_section(machine_id, item)
        body = "\n".join([HR, header, "\n".join(lines), section])
        return "Session Resumed", body

    def format_startup_summary(
        self, *, items: Sequence[Dict[str, Any]]
    ) -> Tuple[str, str]:
        header = self._h2("Startup Summary")
        sections: List[str] = []
        for it in items:
            machine_id = it["machine_id"]
            sections.append(self._machine_section(machine_id, it))
        body = "\n".join([HR, header, "\n".join(sections)])
        return "Startup Summary", body

    def format_error(
        self, *, machine_id: int, error: str, mention: Optional[str] = None
    ) -> Tuple[str, str]:
        header = self._h2("Machine Error")
        lines: List[str] = [
            f"Machine {machine_id}",
            f"Error: {error}",
        ]
        body = "\n".join([HR, header, "\n".join(lines)])
        return "Machine Error", body

    def format_recovery(self, *, machine_id: int) -> Tuple[str, str]:
        header = self._h2("Machine Recovered")
        lines: List[str] = [f"Machine {machine_id}", "Status: OK"]
        body = "\n".join([HR, header, "\n".join(lines)])
        return "Machine Recovered", body

    def _machine_summary(self, machine_id: int, snapshot: Dict[str, Any]) -> str:
        sessions = snapshot.get("sessions", {}) if isinstance(snapshot, dict) else {}
        occ = (snapshot.get("gpu_occupancy") or "").split()
        used = sum(1 for t in occ if t and t != "x")
        total = len(occ) if occ else snapshot.get("num_gpus", 0)
        gpu_total_hr = 0.0
        disk_total_hr = 0.0
        for s in sessions.values():
            gh, dh, _ = self._session_hourly(s)
            gpu_total_hr += gh
            disk_total_hr += dh
        lines: List[str] = [
            f"Machine {machine_id} summary:",
            f"Occupancy: {used}/{total} GPUs",
            f"Active sessions: {len(sessions)}; est hourly {gpu_total_hr:.4f}$ (GPUs) + {disk_total_hr:.4f}$ (disk) = {(gpu_total_hr+disk_total_hr):.4f}$",
        ]
        if not sessions:
            lines.append("- No active sessions")
        else:
            for sid, s in sessions.items():
                gpus = sorted(s.get("gpus", []))
                gh, dh, th = self._session_hourly(s)
                lines.append(f"- {sid}:")
                if gpus:
                    gr = self._current_gpu_rate(s)
                    t = s.get("gpu_type") or "?"
                    lines.append(f"  - GPUs: x{len(gpus)} {gpus} {t} @ {gr:.4f}$/GPU/hr")
                storage_gb = float(s.get("storage_gb", 0.0) or 0.0)
                if storage_gb:
                    sr = self._current_storage_rate(s)
                    lines.append(f"  - Storage: {storage_gb:.2f} GB @ {sr:.4f}$/GB/mo")
                lines.append(
                    f"  - Est hourly: {gh:.4f}$ (GPUs) + {dh:.4f}$ (disk) = {th:.4f}$"
                )
                # Earnings
                gt, dt, tt = self._session_totals(s)
                lines.append(
                    f"  - Earnings: {gt:.4f}$ (GPUs) + {dt:.4f}$ (disk) = {tt:.4f}$"
                )
        return "\n".join(lines)


    def _machine_section(self, machine_id: int, it: Dict[str, Any]) -> str:
        num_gpus = it["num_gpus"]
        occ_str = it["gpu_occupancy"]
        snapshot = it["snapshot"]
        sessions = snapshot.get("sessions", {}) if isinstance(snapshot, dict) else {}
        occ_tokens = occ_str.split()
        used = sum(1 for t in occ_tokens if t != "x")
        pct = int(round((used / num_gpus * 100))) if num_gpus else 0
        session_items: List[tuple[str, Dict[str, Any], str]] = []
        gpu_total_hr = 0.0
        disk_total_hr = 0.0
        for sid, session in sessions.items():
            status = (session.get("status") or "running").lower()
            session_items.append((sid, session, status))
            gh, dh, _ = self._session_hourly(session)
            gpu_total_hr += gh
            disk_total_hr += dh
        running_count = sum(1 for _, _, status in session_items if status != "stored")
        stored_count = sum(1 for _, _, status in session_items if status == "stored")
        lines: List[str] = [
            self._h3(f"Machine {machine_id}"),
            f"Occupancy: {used}/{num_gpus} GPUs ({pct}%)",
            f"Total est hourly: {gpu_total_hr:.4f}$ (GPUs) + {disk_total_hr:.4f}$ (disk) = {(gpu_total_hr+disk_total_hr):.4f}$",
            f"Tracked sessions: {running_count} running, {stored_count} stored",
        ]
        if not session_items:
            lines.append("- No tracked sessions")
        else:
            for sid, session, status in session_items:
                gpus = sorted(session.get("gpus", []))
                gh, dh, th = self._session_hourly(session)
                started_iso = session.get("start_time")
                lines.append(f"- {sid} ({status})")
                if gpus:
                    gr = self._current_gpu_rate(session)
                    t = session.get("gpu_type") or "?"
                    if status == "stored":
                        lines.append(f"  - GPUs (inactive): x{len(gpus)} {gpus} {t}")
                    else:
                        lines.append(f"  - GPUs: x{len(gpus)} {gpus} {t} @ {gr:.4f}$/GPU/hr")
                storage_gb = float(session.get("storage_gb", 0.0) or 0.0)
                if storage_gb:
                    sr = self._current_storage_rate(session)
                    lines.append(f"  - Storage: {storage_gb:.2f} GB @ {sr:.4f}$/GB/mo")
                lines.append(
                    f"  - Est hourly: {gh:.4f}$ (GPUs) + {dh:.4f}$ (disk) = {th:.4f}$"
                )
                gt, dt, tt = self._session_totals(session)
                lines.append(
                    f"  - Earnings: {gt:.4f}$ (GPUs) + {dt:.4f}$ (disk) = {tt:.4f}$"
                )
                lines.append(f"  - Start: {started_iso or ''}")
        return "\n".join(lines)

    def _session_block(
        self, *, session: Dict[str, Any], rental_type: str, rate: float
    ) -> List[str]:
        sid = session.get("client_id")
        gpus = sorted(session.get("gpus", []))
        gcount = len(gpus)
        est_hourly = rate * gcount
        storage_gb = float(session.get("storage_gb", 0.0))
        ssegs = session.get("storage_segments", [])
        cur_storage_rate = None
        if ssegs:
            for seg in reversed(ssegs):
                if seg.get("end") is None:
                    cur_storage_rate = float(seg.get("rate_per_gb_month", 0.0))
                    break
        storage_hourly = ((cur_storage_rate or 0.0) * storage_gb) / 730.0
        total_hourly = est_hourly + storage_hourly
        started_iso = session.get("start_time")
        out: List[str] = []
        out.append(f"- {sid}:")
        out.append(
            f"  - {rental_type} @ ${rate:.4f}/gpu (est hourly {est_hourly:.4f}$ (GPUs) + {storage_hourly:.4f}$ (disk) = {total_hourly:.4f}$)"
        )
        out.append(f"  - x{gcount} GPUs allocated: {gpus}")
        if storage_gb:
            out.append(
                f"  - Storage: {storage_gb:.2f} GB @ {(cur_storage_rate or 0.0):.4f}$/GB/mo"
            )
        out.append(f"  - Start: {started_iso or ''}")
        return out

    def _session_block_end(self, *, session: Dict[str, Any]) -> List[str]:
        sid = session.get("client_id")
        gpus = sorted(session.get("gpus", []))
        gcount = len(gpus)
        earned = float(session.get("estimated_earnings") or 0.0)
        dur = float(session.get("rental_duration") or 0)
        dur_h = humanize_duration(dur)
        started_iso = session.get("start_time") or ""
        ended_iso = session.get("end_time") or ""
        out: List[str] = []
        out.append(f"- {sid}:")
        out.append(f"  - x{gcount} GPUs released: {gpus}")
        out.append(f"  - Duration: {dur_h}")
        gpu_total = float(session.get("earned_gpu", 0.0))
        storage_total = float(session.get("earned_storage", 0.0))
        if gpu_total or storage_total:
            out.append(
                f"  - Total earned: {gpu_total:.4f}$ (GPUs) + {storage_total:.4f}$ (disk) = {(gpu_total+storage_total):.4f}$"
            )
        else:
            out.append(f"  - Total earned: ${earned:.4f}")
        out.append(f"  - Start: {started_iso}")
        out.append(f"  - End: {ended_iso}")
        return out

    # Helpers
    def _current_storage_rate(self, session: Dict[str, Any]) -> float:
        ssegs = session.get("storage_segments", [])
        if ssegs:
            for seg in reversed(ssegs):
                if seg.get("end") is None:
                    return float(seg.get("rate_per_gb_month", 0.0) or 0.0)
        return 0.0

    def _session_hourly(self, session: Dict[str, Any]) -> tuple[float, float, float]:
        gpus = session.get("gpus", []) or []
        gsegs = session.get("gpu_segments", [])
        gpu_rate = 0.0
        if gsegs:
            for seg in reversed(gsegs):
                if seg.get("end") is None:
                    gpu_rate = float(seg.get("rate", 0.0) or 0.0)
                    break
        gpu_hr = gpu_rate * len(gpus) if gpus else 0.0
        storage_gb = float(session.get("storage_gb", 0.0) or 0.0)
        storage_rate = self._current_storage_rate(session)
        disk_hr = (storage_rate * storage_gb) / 730.0 if storage_gb else 0.0
        return gpu_hr, disk_hr, gpu_hr + disk_hr

    def _current_gpu_rate(self, session: Dict[str, Any]) -> float:
        gsegs = session.get("gpu_segments", [])
        if gsegs:
            for seg in reversed(gsegs):
                if seg.get("end") is None:
                    return float(seg.get("rate", 0.0) or 0.0)
        return 0.0

    def _session_totals(self, session: Dict[str, Any]) -> tuple[float, float, float]:
        now_ts = datetime.now(timezone.utc)
        gpu_total = 0.0
        for seg in session.get("gpu_segments", []) or []:
            try:
                start = datetime.fromisoformat(seg.get("start"))
                end_raw = seg.get("end")
                end = datetime.fromisoformat(end_raw) if end_raw else now_ts
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
                end_raw = seg.get("end")
                end = datetime.fromisoformat(end_raw) if end_raw else now_ts
                secs = max(0.0, (end - start).total_seconds())
                rate = float(seg.get("rate_per_gb_month", 0.0) or 0.0)
                storage_total += (rate * storage_gb) * (secs / (730.0 * 3600.0))
            except Exception:
                continue
        return gpu_total, storage_total, gpu_total + storage_total
