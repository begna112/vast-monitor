#!/bin/sh
set -e
CONFIG_PATH="/config/config.json"
exec python vast_monitor.py --config "$CONFIG_PATH" "$@"
