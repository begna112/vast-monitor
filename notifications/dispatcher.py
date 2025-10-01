from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from apprise import Apprise  # type: ignore
from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    retry_if_exception_type,
    retry_if_result,
)

from notifications import get_service
from Classes.app_config import AppriseTarget, AppConfig

EVENT_SYSTEM = "system"
EVENT_STARTUP = "startup"
EVENT_RENTAL_START = "rental_start"
EVENT_RENTAL_END = "rental_end"
EVENT_RENTAL_PAUSE = "rental_pause"
EVENT_RENTAL_RESUME = "rental_resume"
EVENT_ERROR = "error"
EVENT_RECOVERY = "recovery"

VALID_EVENTS: Set[str] = {
    EVENT_SYSTEM,
    EVENT_STARTUP,
    EVENT_RENTAL_START,
    EVENT_RENTAL_END,
    EVENT_RENTAL_PAUSE,
    EVENT_RENTAL_RESUME,
    EVENT_ERROR,
    EVENT_RECOVERY,
}


@dataclass
class NotificationTarget:
    name: str
    url: str
    service: str
    mention: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    events: Optional[Set[str]] = None


class NotificationManager:
    def __init__(
        self,
        app: Any,
        targets: List[NotificationTarget],
        *,
        default_error_mention: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._app = app
        self._targets = targets
        self._logger = logger or logging.getLogger("VastMonitor")
        self._service_cache: Dict[str, Any] = {}
        worker_count = min(8, max(len(targets), 1))
        self._executor = ThreadPoolExecutor(max_workers=worker_count)
        self._default_error_mention = default_error_mention

    def close(self) -> None:
        self._executor.shutdown(wait=True)

    def _service_for(self, key: str):
        cache_key = (key or "default").lower()
        if cache_key not in self._service_cache:
            self._service_cache[cache_key] = get_service(cache_key)
        return self._service_cache[cache_key]

    def _notify_target(
        self,
        target: NotificationTarget,
        title: str,
        body: str,
        *,
        max_attempts: int = 3,
    ) -> bool:
        logger = self._logger

        def _attempt_once() -> bool:
            return bool(self._app.notify(title=title, body=body, tag=target.name))

        @retry(
            stop=stop_after_attempt(3 if max_attempts is None else max_attempts),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=(
                retry_if_exception_type(Exception)
                | retry_if_result(lambda ok: ok is False)
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _attempt_with_retry() -> bool:
            return _attempt_once()

        try:
            ok = _attempt_with_retry()
        except RetryError as exc:  # pragma: no cover - runtime logging
            cause = exc.last_attempt.exception() or exc
            logger.error("Notification delivery failed for %s: %s", target.name, cause)
            return False

        if not ok:
            logger.error(
                "Notification delivery failed for %s after retries",
                target.name,
            )
        return ok

    def _dispatch(
        self,
        formatter_name: str,
        payload: Dict[str, Any],
        *,
        event_type: str,
        include_mention: bool = False,
        max_attempts: int = 3,
    ) -> None:
        for target in self._targets:
            if not target.enabled:
                continue
            if target.events is not None and event_type not in target.events:
                continue
            service = self._service_for(target.service)
            kwargs = dict(payload)
            if include_mention:
                mention = target.mention
                if mention is None and target.service.startswith("discord"):
                    mention = self._default_error_mention
                kwargs["mention"] = mention
            formatter = getattr(service, formatter_name, None)
            if formatter is None:
                self._logger.warning(
                    "Service %s missing formatter %s; skipping target %s",
                    target.service,
                    formatter_name,
                    target.name,
                )
                continue
            try:
                payload_result = formatter(**kwargs)
            except Exception as exc:  # pragma: no cover - runtime logging
                self._logger.warning(
                    "Failed to format notification for %s (%s): %s",
                    target.name,
                    formatter_name,
                    exc,
                )
                continue

            if isinstance(payload_result, tuple):
                messages = [payload_result]
            elif isinstance(payload_result, list):
                messages = list(payload_result)
            else:
                self._logger.warning(
                    "Formatter %s for target %s returned unsupported payload %r",
                    formatter_name,
                    target.name,
                    payload_result,
                )
                continue

            normalized: list[tuple[str, str]] = []
            for entry in messages:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    self._logger.warning(
                        "Formatter %s for target %s returned invalid entry %r",
                        formatter_name,
                        target.name,
                        entry,
                    )
                    continue
                title, body = entry
                if not isinstance(title, str) or not isinstance(body, str):
                    self._logger.warning(
                        "Formatter %s for target %s returned non-string payload %r",
                        formatter_name,
                        target.name,
                        entry,
                    )
                    continue
                normalized.append((title, body))

            for title, body in normalized:
                self._executor.submit(
                    self._notify_target,
                    target,
                    title,
                    body,
                    max_attempts=max_attempts,
                )

    # Public API ---------------------------------------------------------
    def send_system_message(
        self,
        *,
        title: str,
        lines: Sequence[str],
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_system_message",
            {"title": title, "lines": lines},
            event_type=EVENT_SYSTEM,
            max_attempts=max_attempts,
        )

    def send_startup_summary(
        self,
        *,
        items: Sequence[Dict[str, Any]],
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_startup_summary",
            {"items": items},
            event_type=EVENT_STARTUP,
            max_attempts=max_attempts,
        )

    def send_event_start(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        rental_type: str,
        rate: float,
        indices: Sequence[int],
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_event_start",
            {
                "machine_id": machine_id,
                "session": session,
                "snapshot": snapshot,
                "rental_type": rental_type,
                "rate": rate,
                "indices": indices,
            },
            event_type=EVENT_RENTAL_START,
            max_attempts=max_attempts,
        )

    def send_event_end(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_event_end",
            {"machine_id": machine_id, "session": session, "snapshot": snapshot},
            event_type=EVENT_RENTAL_END,
            max_attempts=max_attempts,
        )

    def send_event_pause(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_event_pause",
            {"machine_id": machine_id, "session": session, "snapshot": snapshot},
            event_type=EVENT_RENTAL_PAUSE,
            max_attempts=max_attempts,
        )

    def send_event_resume(
        self,
        *,
        machine_id: int,
        session: Dict[str, Any],
        snapshot: Dict[str, Any],
        rate: float,
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_event_resume",
            {
                "machine_id": machine_id,
                "session": session,
                "snapshot": snapshot,
                "rate": rate,
            },
            event_type=EVENT_RENTAL_RESUME,
            max_attempts=max_attempts,
        )

    def send_error(
        self,
        *,
        machine_id: int,
        error: str,
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_error",
            {"machine_id": machine_id, "error": error},
            event_type=EVENT_ERROR,
            include_mention=True,
            max_attempts=max_attempts,
        )

    def send_recovery(
        self,
        *,
        machine_id: int,
        max_attempts: int = 3,
    ) -> None:
        self._dispatch(
            "format_recovery",
            {"machine_id": machine_id},
            event_type=EVENT_RECOVERY,
            max_attempts=max_attempts,
        )


def _coerce_targets(raw_targets: Iterable[Any], logger: logging.Logger) -> List[AppriseTarget]:
    coerced: List[AppriseTarget] = []
    for entry in raw_targets:
        try:
            if isinstance(entry, AppriseTarget):
                coerced.append(entry)
            elif isinstance(entry, str):
                coerced.append(AppriseTarget(url=entry))
            elif isinstance(entry, dict):
                coerced.append(AppriseTarget(**entry))
            else:
                logger.warning("Unsupported Apprise target %r; skipping", entry)
        except Exception as exc:  # pragma: no cover - runtime logging
            logger.warning("Invalid Apprise target %r: %s", entry, exc)
        else:
            continue
    return coerced


def _normalize_events(
    raw_events: Optional[Iterable[Any]],
    *,
    name: str,
    logger: logging.Logger,
) -> Optional[Set[str]]:
    if not raw_events:
        return None
    if isinstance(raw_events, (str, bytes)):
        raw_iter = [raw_events]
    else:
        raw_iter = list(raw_events)
    event_set: Set[str] = set()
    for ev in raw_iter:
        ev_norm = str(ev).strip().lower()
        if not ev_norm:
            continue
        if ev_norm in {"*", "all", "any"}:
            return None  # subscribe to everything
        if ev_norm not in VALID_EVENTS:
            logger.warning(
                "Target %s specifies unknown event '%s'; skipping that entry",
                name,
                ev,
            )
            continue
        event_set.add(ev_norm)
    return event_set or None


def create_notification_manager(
    config: AppConfig,
    logger: logging.Logger,
) -> Optional[NotificationManager]:
    app = Apprise()
    raw_targets = config.apprise.targets or []
    targets: List[NotificationTarget] = []
    default_mention = config.apprise.error_mention
    service_counts: Dict[str, int] = {}
    existing_names: Set[str] = set()

    for target_cfg in _coerce_targets(raw_targets, logger):
        if not target_cfg.enabled:
            continue
        url = target_cfg.url
        if not url:
            logger.warning("Skipping Apprise target without URL: %r", target_cfg)
            continue

        if "://" in url:
            scheme = url.split("://", 1)[0] or "default"
        else:
            scheme = "default"
        service = (target_cfg.service or scheme).lower() or "default"
        service_counts[service] = service_counts.get(service, 0) + 1

        base_name = target_cfg.name or f"{service}-{service_counts[service]}"
        name = base_name
        suffix = 1
        while name in existing_names:
            suffix += 1
            name = f"{base_name}-{suffix}"

        tags = [name]
        if target_cfg.tags:
            tags.extend(t for t in target_cfg.tags if t != name)

        events = _normalize_events(target_cfg.events, name=name, logger=logger)

        try:
            app.add(url, tag=tags)
        except Exception as exc:  # pragma: no cover - runtime logging
            logger.warning("Failed to add Apprise target '%s': %s", name, exc)
            continue

        targets.append(
            NotificationTarget(
                name=name,
                url=url,
                service=service,
                mention=target_cfg.mention,
                tags=tags,
                events=events,
            )
        )
        existing_names.add(name)

    if not targets:
        logger.info("No enabled notification targets; notifications disabled.")
        return None

    logger.info(
        "Notifications enabled for %d target(s): %s",
        len(targets),
        ", ".join(t.name for t in targets),
    )
    return NotificationManager(
        app=app,
        targets=targets,
        default_error_mention=default_mention,
        logger=logger,
    )
