from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union


class AppriseTarget(BaseModel):
    url: str
    name: Optional[str] = None  # human-friendly label / tag
    enabled: bool = True
    service: Optional[str] = None  # override notification service (defaults to URL scheme)
    mention: Optional[str] = None  # e.g., Discord user ID for discord://
    tags: Optional[List[str]] = None  # optional apprise tags to group targets
    events: Optional[List[str]] = None  # optional list of event types this target should receive


class AppriseConfig(BaseModel):
    # Each target may be a simple URL string or an object with extra properties
    targets: List[Union[str, AppriseTarget]] = Field(default_factory=list)
    error_mention: Optional[str] = (
        None  # legacy: global mention (e.g., Discord user ID)
    )


class NotifyConfig(BaseModel):
    on_startup_existing: bool = False
    on_start: bool = True
    on_shutdown: bool = True
    error_ping_interval_minutes: int = Field(default=60, ge=1)


class AppConfig(BaseModel):
    api_key: str
    machine_ids: List[int]
    log_file: str
    check_frequency: int = Field(..., ge=60)  # seconds
    # Structured config only
    apprise: AppriseConfig = Field(default_factory=AppriseConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    debug: bool = False

    @field_validator("log_file")
    @classmethod
    def validate_log_file(cls, v: str) -> str:
        if not v.endswith(".log"):
            raise ValueError("log_file must end in .log")
        return v

    # No legacy webhook validation; use Apprise targets
