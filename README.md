# Edge Task Hub

Edge Task Hub is a web application for Raspberry Pi edge devices that lets non-technical users configure scheduled tasks with AI-ready notifications—without editing code or cron files. Tasks push reminders, RSS digests, and system health reports to Lark/Feishu custom bots, turning “developer-only automation” into a click-through dashboard experience suitable for Edge AI coursework and production edge ops.

## Why this project exists

Traditional edge automation on a Pi often means SSH, editing JSON, and managing separate schedulers. Edge Task Hub unifies **task configuration**, **scheduling**, **execution history**, and **device monitoring** in one polished UI—making edge AI systems approachable for operators who are not Python developers.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (Tailwind + Alpine.js + Chart.js)                       │
│  Dashboard · Tasks · System · Anomaly Detection · Settings       │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP
┌────────────────────────────▼─────────────────────────────────────┐
│  FastAPI + Jinja2 (pages + JSON API)                             │
│  ┌─────────────┐  ┌──────────────────────────────────────────┐  │
│  │ APScheduler │→ │ Executors: reminder / rss / system_status │  │
│  └─────────────┘  │   reminder: use_ai? → local_llm (Ollama)  │  │
│                   │              else → static payload text  │  │
│                   └──────────────────┬───────────────────────┘  │
│                                      │ notifier.py → Feishu    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Background Anomaly Loop (every 60s)                     │  │
│  │   psutil → SystemMetric table → IsolationForest predict   │  │
│  │   anomaly? → TaskRun (anomaly_alert) + Feishu (30m cap)   │  │
│  │   daily 03:00 → retrain on last 7 days (≥100 samples)    │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
        Lark/Feishu Webhook · SQLite · Ollama (127.0.0.1:11434)
```

## Edge AI

Edge Task Hub runs on-device AI modules with no cloud dependency for model inference:

| Module | Technology | Latency | Role |
|--------|------------|---------|------|
| **Local LLM** | Ollama `qwen3:1.7b` for summaries, smaller models for quick prompts | 30s–5min depending on model and cold start | News and private document summaries are generated locally on the Pi. Reminder tasks can also use local AI when enabled. |
| **Anomaly detection** | scikit-learn `IsolationForest` in `app/ai/anomaly_detector.py` | &lt;100ms per sample | Every 60s collects CPU, memory, disk, temperature, and network features; scores anomalies in real time; retrains daily at 03:00 from the last 7 days of metrics. |

This demonstrates classic **edge AI trade-offs**: a small LLM fits on a Pi but is slow; a lightweight ML model is fast enough for continuous monitoring but needs historical samples before it is useful.

## Feishu inbound automation

The outbound webhook sends reminders and summaries to Feishu. A Feishu custom app can also call `POST /api/feishu/events` so users can create reminders or send private files to the Pi.

Text reminder examples:

```text
remind me tomorrow at 12:00 to eat lunch
remind me every day at 23:30 to sleep
remind me 2026-05-29 at 12:00 to check the Pi
```

Private document flow:

1. Send a `.txt`, `.md`, `.docx`, or text-based `.pdf` file to the Feishu bot.
2. The Pi downloads the file, extracts text locally, deletes the temporary file, and summarizes with local Ollama.
3. The summary is replied back to Feishu. The original document text is not sent to a cloud model.

Required `.env` values for inbound Feishu events:

```bash
FEISHU_INBOUND_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
FEISHU_ALLOWED_OPEN_IDS=ou_xxx
```

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Uvicorn, APScheduler, SQLAlchemy, SQLite |
| Frontend | Jinja2, Tailwind CSS, Alpine.js, Chart.js, HTMX, Lucide |
| Integrations | feedparser (RSS), requests (webhook), psutil (metrics) |

## Directory structure

```
edge-task-hub/
├── app/
│   ├── main.py              # FastAPI entry + lifespan
│   ├── config.py            # Settings from .env
│   ├── database.py          # SQLAlchemy engine
│   ├── models.py            # Task, TaskRun tables
│   ├── scheduler.py         # APScheduler wiring
│   ├── notifier.py          # Lark/Feishu sender
│   ├── system_monitor.py    # CPU/memory/disk/temp
│   ├── executors/           # reminder, rss_digest, system_status
│   ├── routes/              # API + HTML pages
│   └── templates/           # Jinja2 UI
├── static/                  # CSS/JS
├── data/                    # SQLite database
├── .env                     # Secrets (not committed)
├── requirements.txt
└── systemd/edge-task-hub.service
```

## Quick start

### Install

```bash
cd ~/edge-task-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set FEISHU_WEBHOOK_URL
```

### Run (development)

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<pi-ip>:8000` in your browser.

### Run (systemd user service)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/edge-task-hub.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now edge-task-hub
loginctl enable-linger $USER
```

### Stop / logs

```bash
systemctl --user stop edge-task-hub
systemctl --user status edge-task-hub
journalctl --user -u edge-task-hub -f
```

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks` | List all tasks |
| POST | `/api/tasks` | Create task (JSON body) |
| GET | `/api/tasks/{id}` | Get task |
| PUT | `/api/tasks/{id}` | Update task |
| DELETE | `/api/tasks/{id}` | Delete task |
| POST | `/api/tasks/{id}/toggle` | Enable/disable |
| POST | `/api/tasks/{id}/run` | Run now |
| GET | `/api/tasks/{id}/runs` | Execution history |
| GET | `/api/stats/dashboard` | Dashboard stats |
| GET | `/api/system/snapshot` | Live metrics |
| GET | `/api/system/cpu-history` | CPU ring buffer |
| GET | `/api/system/services` | Ollama/OpenClaw/scheduler status |
| GET | `/api/anomaly/stats` | Model status, sample count, 24h anomalies |
| GET | `/api/anomaly/series` | Anomaly score time series (24h) |
| GET | `/api/anomaly/events` | Recent anomaly events |
| POST | `/api/anomaly/train` | Manual model retrain |
| POST | `/api/feishu/events` | Feishu inbound event callback for reminder commands and private document summaries |

## Screenshots

<!-- Add screenshots here after deployment -->

## License

Private / course use.
