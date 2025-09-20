import argparse
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

import vastai_sdk

from Classes.app_config import AppConfig
from monitoring.state import StatePaths, ensure_state_dirs
from monitoring.loop import start_monitoring
from notifications.dispatcher import NotificationManager, create_notification_manager
from notifications.utils import discord_ts


def load_config(config_path: Path) -> AppConfig:
    with config_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return AppConfig(**raw)


def setup_logger(log_path: Path, debug: bool = False) -> logging.Logger:
    logger = logging.getLogger("VastMonitor")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    log_path = log_path.expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    from logging.handlers import TimedRotatingFileHandler

    if not any(isinstance(h, TimedRotatingFileHandler) for h in logger.handlers):
        file_handler = TimedRotatingFileHandler(str(log_path), when="midnight", backupCount=7)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    ):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Vast.ai machines.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.cwd() / "config.json",
        help="Path to configuration file (default: ./config.json).",
    )
    args = parser.parse_args()

    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    paths = StatePaths.for_base_dir(config_path.parent)
    ensure_state_dirs(paths)

    config = load_config(config_path)

    log_path = Path(config.log_file)
    if not log_path.is_absolute():
        log_path = paths.base_dir / log_path
    logger = setup_logger(log_path, config.debug)

    logger.info("Loaded config for %s machine(s).", len(config.machine_ids))
    logger.info("State directory: %s", paths.base_dir)
    logger.info("Snapshots will be saved to: %s", paths.snapshots_dir)
    logger.info("Rental logs will be saved to: %s", paths.rental_logs_dir)
    logger.info("Rental snapshot file: %s", paths.rental_snapshot_path)

    vastai = vastai_sdk.VastAI(config.api_key)

    try:
        notifier = create_notification_manager(config, logger)
    except Exception as exc:  # pragma: no cover - runtime logging
        logger.warning("Notifier setup failed: %s", exc)
        notifier = None

    if config.notify.on_start and notifier is not None:
        started_iso = datetime.now(timezone.utc).isoformat()
        lines = [
            f"Monitor started at {discord_ts(started_iso, 'f')} ({discord_ts(started_iso, 'R')})",
            f"Machines: {config.machine_ids}",
            f"Check frequency: {config.check_frequency}s",
        ]
        notifier.send_system_message(title="Monitor Started", lines=lines)

    try:
        start_monitoring(
            config=config,
            logger=logger,
            vastai=vastai,
            paths=paths,
            notifier=notifier,
        )
    except KeyboardInterrupt:
        logger.info("Exiting.")
        if config.notify.on_shutdown and notifier is not None:
            stopped_iso = datetime.now(timezone.utc).isoformat()
            lines = [
                f"Monitor stopped at {discord_ts(stopped_iso, 'f')} ({discord_ts(stopped_iso, 'R')})",
            ]
            notifier.send_system_message(title="Monitor Stopped", lines=lines)
    except Exception as exc:
        logger.exception("Fatal error in monitor loop: %s", exc)
        if config.notify.on_shutdown and notifier is not None:
            stopped_iso = datetime.now(timezone.utc).isoformat()
            lines = [
                f"Monitor crashed at {discord_ts(stopped_iso, 'f')} ({discord_ts(stopped_iso, 'R')})",
                f"Reason: {exc.__class__.__name__}: {exc}",
            ]
            notifier.send_system_message(title="Monitor Crashed", lines=lines)
        raise
    finally:
        if notifier is not None:
            notifier.close()


if __name__ == "__main__":
    main()
