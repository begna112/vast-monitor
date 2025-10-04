# Vast Monitor

Vast Monitor tracks selected Vast.ai machines, watches rental activity, and delivers real-time notifications when sessions start, pause, resume, end, or when machines report errors. It keeps a lightweight local snapshot of machine state for continuity and can notify multiple channels in parallel via [Apprise](https://github.com/caronc/apprise).

## Installing the Monitor

1. Clone the repository:
   ```bash
   git clone https://github.com/begna112/vast-monitor.git
   cd vast-monitor
   ```
2. Copy the example config and edit it (see [Configuration](#configuration)).
3. Install dependencies (`pip install -r requirements.txt`) either in a virtualenv or globally (see [Requirements](#requirements)).
4. Run the monitor with your config:
   ```bash
   python vast_monitor.py --config /path/to/config.json
   ```

The project is designed to run directly from the cloned folder—no packaging step is required.

## Updating the Monitor

1. Pull the repository:
   ```bash
   cd vast-monitor
   git pull --rebase
   ```
2. Stop and start the script again. 
   
## Requirements

- Python 3.10 or newer
- Vast.ai account with API key
- Optional: Apprise-compatible notification endpoints (Discord, email, etc.)

Install Python dependencies with your preferred workflow:

### Using a virtual environment (recommended)
```bash
python -m venv .venv
. .venv/bin/activate  # or Scripts/activate on Windows
pip install -r requirements.txt
```

### Installing globally (not recommended, but available)
```bash
pip install --user -r requirements.txt
```

## Configuration

1. Copy the sample config and adapt it to your environment:
   ```bash
   mkdir -p ~/.config/vast-monitor
   cp examples/config.example.json ~/.config/vast-monitor/config.json
   ```
2. Edit the copy to provide:
   - `api_key`: your Vast.ai API key
   - `machine_ids`: list of machines to monitor
   - `apprise.targets`: one entry per notification target. Each target supports:
     - `url`: Apprise URL (e.g. Discord webhook, SMTP endpoint)
     - `service`: overrides the formatter (`discord`, `email`, etc.)
     - `events`: optional event whitelist. Use `"all"` or omit to receive every event.
   - `log_file`: log filename (relative paths resolve against the state directory)
   - `notify`: toggle startup/shutdown/error notifications

All config keys mirror `examples/config.example.json`.

## Running the Monitor

### Running Locally

The monitor stores everything next to your config file. For example:

```bash
python vast_monitor.py --config ~/.config/vast-monitor/config.json
```

If your config lives at `~/.config/vast-monitor/config.json`, runtime files appear under `~/.config/vast-monitor/` in these locations:
- `machine_snapshots/` — latest machine payloads per ID
- `rental_snapshot.json` — session tracking per machine
- `rental_logs/` — archived session payloads
- `vast_monitor.log` — rolling log file (rotated nightly)

### Running with Docker

Pre-built images are published to GitHub Container Registry. Create a directory **outside this repository** to hold your config and runtime state (for example `~/vastmonitor-config/`), place your `config.json` there, then start the container:

```bash
mkdir -p ~/vastmonitor-config
cp /path/to/your/config.json ~/vastmonitor-config/config.json
docker pull ghcr.io/begna112/vast-monitor:latest
docker run --rm \
  -v ~/vastmonitor-config:/config \
  ghcr.io/begna112/vast-monitor:latest
```

- `/config/config.json` must exist inside the mounted directory and mirrors `examples/config.example.json`.
- Any state or log files created by the monitor stay within the mounted host directory.
- If you need a different filename, append `--config /config/other.json` to the run command.

## Running with Docker Compose (Best for Multiple Vast Accounts)

A sample `compose.yaml` references the image and mounts `./config-primary` by default. Create a config directory **outside the repository** (e.g. `~/vastmonitor-config-primary/`), copy your `config.json` there, and update the volume mapping:

```yaml
services:
  monitor_primary:
    image: ghcr.io/begna112/vast-monitor:latest
    volumes:
      - ~/vastmonitor-config-primary:/config
```

Then launch:

```bash
docker compose up -d
```

To monitor additional machines, create more host directories (`~/vastmonitor-config-secondary/`, etc.), place distinct configs inside, and uncomment the extra services in `compose.yaml`, updating each volume path accordingly.


## Supported Notification Services

Refer to the [Apprise Documentation](https://github.com/caronc/apprise/wiki) as needed for service configuration.

| Service | Scheme(s) | Description |
| --- | --- | --- |
| [Discord](https://github.com/caronc/apprise/wiki/Notify_discord) | `discord://` | Rich markdown formatting with Discord timestamps; supports per-target mentions and full rental summaries. Utilizes Discord Webhooks. |
| [Email](https://github.com/caronc/apprise/wiki/Notify_email) | `mailtos://`, `mailto://` | Plain-text emails rendered in `<pre>` blocks so all sections align; converts Discord timestamps to human-readable text. |
| Default | any other scheme | Fallback plain-text formatter used for services without custom handling. Does nothing. Just here for a baseline for future service handlers. |

## Notification Event Types

Each notification target can subscribe to specific events via the `events` list. Supported values include:

- `system` — startup/shutdown/system messages
- `startup` — initial summary of existing rentals when the monitor launches
- `rental_start` — a new rental was detected
- `rental_end` — a rental fully ended (GPUs released and storage cleared)
- `rental_pause` — GPUs released but storage remains allocated
- `rental_resume` — a paused rental resumed on the machine
- `error` — machine reported an error or timeout
- `recovery` — machine recovered from an error/timeout

Use `"all"` (or omit the list) to receive every event.

## Adding a Custom Notification Service

1. Create a new module under `notifications/services/<your_service>/service.py` that subclasses `BaseService` and implements the formatter methods used by the monitor (`format_system_message`, `format_event_start`, etc.).
2. Register the service in `notifications/registry.py` so the dispatcher can resolve it by URL scheme.
3. Add a target in your config with `service` set to the new scheme and point `url` at an Apprise endpoint that knows how to deliver it.
4. Send a test rental event and submit a pull request once everything formats cleanly.

## Running as a Service (Untested)

### Linux (systemd)
1. Install dependencies in a virtualenv or system-wide.
2. Create a service file `/etc/systemd/system/vast-monitor.service`:
   ```ini
   [Unit]
   Description=Vast Monitor
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/opt/vast-monitor
   ExecStart=/usr/bin/python /opt/vast-monitor/vast_monitor.py --config /etc/vast-monitor/config.json
   Restart=on-failure
   RestartSec=10s

   [Install]
   WantedBy=multi-user.target
   ```
3. Reload and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now vast-monitor
   ```

### Linux (Supervisor)
Install `supervisor` and add program block:
```ini
[program:vast-monitor]
command=/opt/vast-monitor/.venv/bin/python /opt/vast-monitor/vast_monitor.py --config /etc/vast-monitor/config.json
directory=/opt/vast-monitor
autostart=true
aautorestart=true
```
Then reload supervisor.

### Windows (Task Scheduler)
- Create a basic task with `python.exe` and arguments `C:\path\to\vast_monitor.py --config C:\vast-monitor\config.json`.
- Set trigger `At log on` or `At startup` and enable "Run whether user is logged on or not".

### Windows (NSSM)
1. Download NSSM and install service:
   ```powershell
   nssm install VastMonitor "C:\Python311\python.exe" "C:\vast-monitor\vast_monitor.py" --config "C:\vast-monitor\config.json"
   ```
2. Start the service with `nssm start VastMonitor`.

## Sample Data

The `examples/` directory contains sample config and snapshot files that demonstrate the expected structure without exposing real machine details. When running the monitor, always use your own copies outside the repository to avoid overwriting tracked files.

