# Vast Monitor

Vast Monitor tracks selected Vast.ai machines, watches rental activity, and sends real-time notifications when sessions start, pause, resume, end, or when machines report errors. It keeps a lightweight local snapshot of machine state and can notify multiple channels in parallel via [Apprise](https://github.com/caronc/apprise).

## Table of Contents

- [Configuration](#configuration)
  - [Runtime Directory Layout](#runtime-directory-layout)
- [Notifications](#notifications)
  - [Supported Services](#supported-services)
  - [Event Types](#event-types)
  - [Extending Notification Services](#extending-notification-services)
- [Sample Data](#sample-data)
- [Running Locally](#running-locally)
  - [Requirements](#requirements)
  - [Install Dependencies](#install-dependencies)
  - [Launch](#launch)
  - [Updating](#updating)
- [Running with Docker](#running-with-docker)
- [Running with Docker Compose](#running-with-docker-compose-multiple-configs)
- [Running as a Service (untested)](#running-as-a-service-untested)
  - [Linux (systemd)](#linux-systemd)
  - [Linux (Supervisor)](#linux-supervisor)
  - [Windows (Task Scheduler)](#windows-task-scheduler)
  - [Windows (NSSM)](#windows-nssm)
- [Release Workflow (for maintainers)](#release-workflow-for-maintainers)

---

## Configuration

All deployment methods share the same JSON schema as `examples/config.example.json`.

Copy the example config outside this repository and edit it:

Linux:
```bash
mkdir -p ~/.config/vast-monitor
curl -fsSL https://raw.githubusercontent.com/begna112/vast-monitor/main/examples/config.example.json \
  -o ~/.config/vast-monitor/config.json
```

Windows:
```Powershell
New-Item -Path "$env:USERPROFILE\.config\vast-monitor" -ItemType Directory -Force
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/begna112/vast-monitor/main/examples/config.example.json" `
  -OutFile "$env:USERPROFILE\.config\vast-monitor\config.json"
```

(Or download the file manually and move it to your preferred location.)

Update the copy with:
- `api_key`: your Vast.ai API key
- `machine_ids`: list of machine IDs to monitor
- `apprise.targets`: one entry per notification target, each with:
  - `url`: Apprise URL (e.g. Discord webhook, SMTP endpoint)
  - `service`: formatter name (`discord`, `email`, etc.)
  - `events`: optional whitelist (`"all"` or omit to receive every event)
- `log_file`, `notify`, and other options as needed

Keep your `config.json` in a directory outside this repository (for example `~/.config/vast-monitor/`). That directory becomes the monitor's runtime workspace.

### Runtime Directory Layout

Assuming your config directory is `<config-dir>` (e.g. `~/.config/vast-monitor/`), the monitor maintains:
- `<config-dir>/config.json` – configuration you maintain
- `<config-dir>/machine_snapshots/` – latest machine payloads
- `<config-dir>/rental_snapshot.json` – session tracking per machine
- `<config-dir>/rental_logs/` – archived session payloads
- `<config-dir>/vast_monitor.log` – rolling log file (rotated nightly)

---

## Notifications

### Supported Services

Refer to the [Apprise documentation](https://github.com/caronc/apprise/wiki) for configuration details.

| Service | Scheme(s) | Description |
| --- | --- | --- |
| [Discord](https://github.com/caronc/apprise/wiki/Notify_discord) | `discord://` | Rich markdown, Discord timestamps, webhook delivery, optional mentions. |
| [Email](https://github.com/caronc/apprise/wiki/Notify_email) | `mailtos://`, `mailto://` | Plain-text emails rendered in `<pre>` blocks, timestamps converted to human-readable forms. |
| Default | any other scheme | Fallback plain-text formatter for services without custom handlers. |

### Event Types

Each notification target can subscribe to specific events with the `events` list:
- `system` – startup/shutdown/system messages
- `startup` – initial rental snapshot summary at launch
- `rental_start` – new rental detected
- `rental_end` – rental fully ended (GPUs released and storage cleared)
- `rental_pause` – GPUs released but storage remains allocated
- `rental_resume` – paused rental resumed
- `error` – machine reported an error or timeout
- `recovery` – machine recovered from an error/timeout

Use `"all"` (or omit the list) to receive every event.

### Extending Notification Services

1. Create `notifications/services/<service>/service.py`, subclass `BaseService`, and implement the formatter methods you need.
2. Register the service in `notifications/registry.py` so the dispatcher resolves it by scheme or explicit `service` name.
3. Add a target in your config with `service` set to the new formatter and point `url` at an Apprise endpoint that can deliver it.

---

## Sample Data

The `examples/` directory contains sample configs and snapshots that demonstrate the expected structure without exposing real machine details. Use your own copies outside the repository to avoid overwriting tracked files.

---

## Running Locally

### Requirements

- Python 3.12 or newer
- Vast.ai account with an API key
- Optional: Apprise-compatible notification endpoints (Discord, email, etc.)

### Install Dependencies

Using a virtual environment (recommended):
```bash
python -m venv .venv
. .venv/bin/activate  # or Scripts/activate on Windows
pip install -r requirements.txt
```

Or globally (not recommended):
```bash
pip install --user -r requirements.txt
```

### Launch

The monitor stores its state next to your config file (see [Runtime Directory Layout](#runtime-directory-layout)).
```bash
python vast_monitor.py --config ~/.config/vast-monitor/config.json
```

### Updating

Pull the latest changes and restart the monitor:
```bash
cd vast-monitor
git pull --rebase
```

---

## Running with Docker

Pre-built images are available at `ghcr.io/begna112/vast-monitor` with the following tags:
- `:latest` – most recent commit to main (bleeding edge)
- `:stable` – latest versioned release (recommended for production)
- `:1.3.0`, `:1.4.0`, etc. – specific versions for pinning

Create a host directory to store `config.json` and runtime files. **This can be any directory you choose** (e.g., `~/vastmonitor-config`, `/opt/vast-monitor`, `C:\vastmonitor`, etc.). The container will mount this directory to `/config` and needs **read/write permissions** to create snapshots, logs, and track state.

**Example setup:**

```bash
# Create your config directory (use any path you prefer)
mkdir -p ~/vastmonitor-config

# Copy your config file
cp /path/to/config.json ~/vastmonitor-config/config.json

# Run the container with stable tag (recommended)
docker pull ghcr.io/begna112/vast-monitor:stable
docker run --rm \
  -v ~/vastmonitor-config:/config \
  ghcr.io/begna112/vast-monitor:stable
```

**Important notes:**
- The host directory you mount (e.g., `~/vastmonitor-config`) can be **any path** on your system
- Docker must have **read and write permissions** to this directory to create logs, snapshots, and track rental state
- `/config/config.json` must exist inside the mounted directory and follow the sample schema
- Runtime files (`machine_snapshots/`, `rental_snapshot.json`, `rental_logs/`, `vast_monitor.log`) will be created automatically in the mounted directory
- Override the config filename with `--config /config/other.json` if needed

**Using different tags:**
```bash
# Latest stable release (recommended)
docker run --rm -v ~/vastmonitor-config:/config ghcr.io/begna112/vast-monitor:stable

# Bleeding edge (most recent commit)
docker run --rm -v ~/vastmonitor-config:/config ghcr.io/begna112/vast-monitor:latest

# Specific version
docker run --rm -v ~/vastmonitor-config:/config ghcr.io/begna112/vast-monitor:1.3.0
```

---

## Running with Docker Compose (multiple configs)

`compose.yaml` demonstrates running multiple monitors simultaneously, each with its own configuration. Create a separate host directory for each monitor (these can be **any paths** you choose), then map them in the compose file.

**Example setup:**

```bash
# Create directories for each monitor (use any paths you prefer)
mkdir -p ~/vastmonitor-config-primary
mkdir -p ~/vastmonitor-config-secondary

# Copy config files to each directory
cp /path/to/config1.json ~/vastmonitor-config-primary/config.json
cp /path/to/config2.json ~/vastmonitor-config-secondary/config.json
```

**Update `compose.yaml`:**

```yaml
services:
  monitor_primary:
    image: ghcr.io/begna112/vast-monitor:stable  # Use :stable, :latest, or specific version
    volumes:
      - ~/vastmonitor-config-primary:/config     # Map your first config directory
    restart: unless-stopped

  monitor_secondary:
    image: ghcr.io/begna112/vast-monitor:stable
    volumes:
      - ~/vastmonitor-config-secondary:/config   # Map your second config directory
    restart: unless-stopped
```

**Start the stack:**
```bash
docker compose up -d
```

**Important notes:**
- Each service needs its own host directory with a `config.json` file
- Directory paths can be **any location** on your system (absolute or relative to the compose file)
- Each directory needs **read/write permissions** for Docker to create logs and snapshots
- You can run as many monitors as needed by adding more services to the compose file
- Use `:stable` tag for production deployments or `:latest` for bleeding edge

---

## Running as a Service (untested)

### Linux (systemd)
1. Install dependencies (virtualenv or system-wide).
2. Create `/etc/systemd/system/vast-monitor.service`:
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
```ini
[program:vast-monitor]
command=/opt/vast-monitor/.venv/bin/python /opt/vast-monitor/vast_monitor.py --config /etc/vast-monitor/config.json
directory=/opt/vast-monitor
autostart=true
aautorestart=true
```
Reload Supervisor to apply the change.

### Windows (Task Scheduler)
- Create a basic task with `python.exe` and arguments `C:\path\to\vast_monitor.py --config C:\vast-monitor\config.json`.
- Trigger on login or startup and enable "Run whether user is logged on or not".

### Windows (NSSM)
```powershell
nssm install VastMonitor "C:\Python311\python.exe" "C:\vast-monitor\vast_monitor.py" --config "C:\vast-monitor\config.json"
nssm start VastMonitor
```

---

## Release Workflow (for maintainers)

This repository uses [release-please](https://github.com/googleapis/release-please). When new commits land on `main`, the GitHub Action opens a "release PR" that bumps the version and updates `CHANGELOG.md`. Merge that PR when you're ready to publish; the workflow automatically tags the repository, publishes the GitHub release, and pushes the Docker image to GHCR.
