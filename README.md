# Edge Task Hub

Edge Task Hub is a Raspberry Pi Edge AI system for scheduled automation, previous-day global news summaries, private document summaries, Feishu reminders, and local device-health anomaly detection.

The Raspberry Pi owns scheduling, inference, document extraction, fallback decisions, metric collection, and anomaly scoring. Feishu is used as the user interaction and notification channel; raw document text is not sent to a cloud LLM.

## Team

| Name | Student ID |
|---|---:|
| Shuaiwu Dong | 1235830 |
| Haoru Ye | 1234742 |
| Bangrui Xiang | 1195193 |

Repository: <https://github.com/JerryshuaiwuDong/edge-task-hub>

## Edge AI contribution

The project does not treat one language model as the answer to every task. It routes work according to latency, quality, privacy, and Raspberry Pi resource limits.

| Workload | Local method | Reason |
|---|---|---|
| Previous-day news summary | Ollama `qwen3:1.7b` | The 10:00 task is scheduled and can wait for higher-quality local output. |
| Private document summary | Ollama `qwen2.5:0.5b-instruct` | Faster response for longer private text while processing remains on the Pi. |
| Reminder parsing fallback | Ollama `qwen3:1.7b` with strict validation | Used only when deterministic parsing cannot resolve a plausible reminder. |
| Short local prompts | Ollama `qwen3:0.6b` candidate | Lower model cost for short interactions. |
| Feed or model failure | Deterministic rules | Keeps failure behavior visible, local, and auditable. |
| Device health | scikit-learn `IsolationForest` | Scores numeric system metrics locally without using an LLM. |

The verified news run used the real Raspberry Pi endpoint with `qwen3:1.7b`, completed in `55.624 s`, reached `2.208 tokens/s`, and returned `fallback=false`.

## Architecture

```text
Browser / Feishu
       |
       v
FastAPI + Jinja2
       |
       +-- APScheduler -> reminder / RSS / system-status executors
       +-- Local Ollama -> news, document, and reminder language tasks
       +-- Rules -> deterministic parsing and explicit failure fallback
       +-- Isolation Forest -> CPU, memory, disk, temperature, network
       +-- SQLite -> tasks, run history, and system metrics
       |
       v
Feishu notification
```

System metrics are sampled every 300 seconds by default. Isolation Forest retrains at 03:00 from the previous seven days when at least 100 samples are available.

## Main workflows

### Previous-day global news

The formal task runs at `0 10 * * *` in `Asia/Shanghai`. It reads the Google News World RSS feed, keeps one recent item per publisher before using duplicate publishers, requires at least ten distinct publishers, filters the previous local calendar day, and summarizes locally. The run record includes the publisher count, source links, backend, model, latency, fallback state, and delivery result.

RSS TLS certificates are always verified. Certificate failures are reported directly; the application never retries with certificate verification disabled.

### Feishu reminders

Supported deterministic examples:

```text
remind me tomorrow at 12:00 to eat lunch
remind me every day at 23:30 to sleep
remind me 2026-06-08 at 12:00 to check the Pi
```

Clear commands use deterministic parsing. A local LLM is only a structured fallback, and its result must pass time and JSON validation before a task is created.

### Private documents

Supported inputs:

- `.txt` and `.md`
- `.docx`
- legacy `.doc` when LibreOffice is installed
- text-based `.pdf`

The Pi downloads the file to a temporary directory, extracts text locally, summarizes with local Ollama, and removes the temporary file. Scanned PDF OCR is outside the verified scope.

### Device-health anomaly detection

The application stores CPU, memory, disk, temperature, and network measurements in SQLite. After enough samples exist, Isolation Forest learns the recent normal pattern and flags unusual combinations. The anomaly page shows model status, scores, recent events, and likely contributing metrics.

## Technology

| Layer | Technology |
|---|---|
| Backend | FastAPI, Uvicorn, APScheduler, SQLAlchemy, SQLite |
| Frontend | Jinja2, Tailwind CSS, Alpine.js, Chart.js, HTMX, Lucide |
| Edge AI | Ollama, Qwen models, scikit-learn Isolation Forest |
| Integrations | Feishu API/webhook, feedparser, requests, psutil |

## Repository structure

```text
app/
  ai/                 Local LLM, routing, RSS, document, and anomaly logic
  executors/          Scheduled task execution
  external_sources/   Read-only views of external schedulers
  feishu/             Feishu client, event parsing, and reminder parsing
  routes/             JSON APIs and HTML pages
  templates/          Web interface
scripts/              Raspberry Pi benchmark and maintenance utilities
systemd/              Raspberry Pi user service definition
tests/                Unit tests
```

## Installation

```bash
cd ~/edge-task-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set at least `FEISHU_WEBHOOK_URL` for outbound notifications. Inbound Feishu reminders and files also require:

```bash
FEISHU_INBOUND_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=replace_me
FEISHU_VERIFICATION_TOKEN=replace_me
FEISHU_ALLOWED_OPEN_IDS=ou_xxx
```

Secrets and runtime databases are excluded by `.gitignore`.

## Run

Development:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

User-level systemd service:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/edge-task-hub.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now edge-task-hub
loginctl enable-linger "$USER"
```

Open `http://<pi-ip>:8000`.

## Verification

```bash
python -m unittest discover -s tests -v
python scripts/check_english_content.py
```

The tests cover news-summary behavior, secure RSS failure handling, Word document extraction, Feishu events, reminder parsing, and OpenClaw credential forwarding.

## API

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/tasks` | List or create tasks |
| GET/PUT/DELETE | `/api/tasks/{id}` | Read, update, or delete a task |
| POST | `/api/tasks/{id}/run` | Run a task immediately |
| GET | `/api/tasks/{id}/runs` | Read execution history |
| GET | `/api/system/snapshot` | Read live Raspberry Pi metrics |
| GET | `/api/system/services` | Read Ollama, OpenClaw, and scheduler state |
| GET | `/api/anomaly/stats` | Read anomaly model status |
| POST | `/api/anomaly/train` | Retrain the anomaly model |
| POST | `/api/feishu/events` | Receive Feishu reminders and private files |

## Scope

This repository is the final source-code submission for an Edge AI course project. OpenClaw and the older `pi-scheduler` are optional external sources and are not required for the main Edge Task Hub workflow.
