from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GPUSegment(BaseModel):
    start: str
    end: Optional[str] = None
    rate: float  # $/hr/gpu
    gpu_count: int


class StorageSegment(BaseModel):
    start: str
    end: Optional[str] = None
    rate_per_gb_month: float  # $/GB/mo


class RentalSession(BaseModel):
    client_id: str
    status: Literal["running", "stored"] = "running"
    gpus: List[int]
    start_time: str = Field(default_factory=now_iso)
    last_state_change: str = Field(default_factory=now_iso)

    # Storage
    storage_gb: float = 0.0

    # Contract ceilings
    gpu_contracted_rate: float = 0.0  # $/hr/gpu
    storage_contracted_rate: float = 0.0  # $/GB/mo

    # GPU rental type (D/I/R)
    gpu_type: Optional[str] = None

    # Segments
    gpu_segments: List[GPUSegment] = Field(default_factory=list)
    storage_segments: List[StorageSegment] = Field(default_factory=list)

    # Optional contract end
    client_end_date: Optional[str] = None

    # Back-compat fields populated on finalize for notifications
    end_time: Optional[str] = None
    rental_duration: Optional[float] = None  # seconds
    estimated_earnings: Optional[float] = None  # total (gpu+storage)
    earned_gpu: Optional[float] = None
    earned_storage: Optional[float] = None

    def open_gpu_segment(self, rate_per_gpu_hour: float, gpu_count: int, ts: Optional[str] = None):
        ts = ts or now_iso()
        # close any open segment first
        self.close_gpu_segment(ts)
        self.gpu_segments.append(
            GPUSegment(start=ts, rate=rate_per_gpu_hour, gpu_count=gpu_count)
        )
        self.last_state_change = ts
        self.status = "running"

    def close_gpu_segment(self, ts: Optional[str] = None):
        ts = ts or now_iso()
        if self.gpu_segments and self.gpu_segments[-1].end is None:
            self.gpu_segments[-1].end = ts
            self.last_state_change = ts

    def open_storage_segment(self, rate_per_gb_month: float, ts: Optional[str] = None):
        ts = ts or now_iso()
        # only open if no open storage segment or new rate is lower
        if self.storage_segments and self.storage_segments[-1].end is None:
            cur = self.storage_segments[-1]
            if rate_per_gb_month >= cur.rate_per_gb_month:
                return
            # close previous and open new at lower rate
            cur.end = ts
        self.storage_segments.append(
            StorageSegment(start=ts, rate_per_gb_month=rate_per_gb_month)
        )

    def close_storage_segment(self, ts: Optional[str] = None):
        ts = ts or now_iso()
        if self.storage_segments and self.storage_segments[-1].end is None:
            self.storage_segments[-1].end = ts

    def to_hourly_estimate(self, current_gpu_rate: float, current_storage_rate: float) -> tuple[float, float, float]:
        # Estimated hourly right now
        gpu_hourly = current_gpu_rate * len(self.gpus)
        # Convert $/GB/mo to $/hr for given GB (730 hrs per month)
        storage_hourly = (current_storage_rate * self.storage_gb) / 730.0
        return gpu_hourly, storage_hourly, gpu_hourly + storage_hourly

    def totals(self, now_ts: Optional[str] = None) -> tuple[float, float, float, float]:
        now_ts = now_ts or now_iso()
        # Duration
        start_dt = datetime.fromisoformat(self.start_time)
        end_dt = datetime.fromisoformat(self.end_time or now_ts)
        duration = (end_dt - start_dt).total_seconds()

        gpu_total = 0.0
        for seg in self.gpu_segments:
            seg_start = datetime.fromisoformat(seg.start)
            seg_end = datetime.fromisoformat(seg.end or now_ts)
            secs = max(0.0, (seg_end - seg_start).total_seconds())
            gpu_total += seg.rate * seg.gpu_count * (secs / 3600.0)

        storage_total = 0.0
        for seg in self.storage_segments:
            seg_start = datetime.fromisoformat(seg.start)
            seg_end = datetime.fromisoformat(seg.end or now_ts)
            secs = max(0.0, (seg_end - seg_start).total_seconds())
            # $/GB/mo to $ for our GB and seconds; 730 hrs/month
            storage_total += (seg.rate_per_gb_month * self.storage_gb) * (secs / (730.0 * 3600.0))

        return duration, gpu_total, storage_total, (gpu_total + storage_total)

    def finalize_end(self):
        self.end_time = now_iso()
        self.close_gpu_segment(self.end_time)
        self.close_storage_segment(self.end_time)
        dur, gpu_total, storage_total, total = self.totals(self.end_time)
        self.rental_duration = dur
        self.estimated_earnings = round(total, 6)
        # expose split totals for formatters
        self.earned_gpu = round(gpu_total, 6)
        self.earned_storage = round(storage_total, 6)
