# Edge Task Hub: Privacy-Preserving Edge AI Task Automation on Raspberry Pi

Authors: to be added before submission

Generated: 2026-05-29T09:50:15+00:00

## Abstract

This paper presents Edge Task Hub, a Raspberry Pi based Edge AI system for scheduled reminders, daily news summaries, private document summaries, and device-health monitoring. The system is built around a local-first privacy boundary: Feishu is used for message delivery and user input, while news summarization, private document summarization, and anomaly detection run on the Raspberry Pi. The final design selects `qwen3:1.7b` for quality-first news and document summaries, keeps `qwen3:0.6b` for shorter local interactions, rejects `qwen3.5:0.8b` for this workload because of cold-start latency and empty visible output, and keeps deterministic rules plus Isolation Forest as edge-safe fallbacks.

## 1. Introduction

The project goal is not to build a general cloud chatbot. The goal is to defend an Edge AI system: a small device collects local data, runs local intelligence, exposes clear scheduling workflows, and sends only the final notification result through Feishu. This matters because the course project must show the edge part of AI, not only the AI part.

Edge Task Hub uses a Raspberry Pi as the edge device. It runs a FastAPI web service, APScheduler jobs, a SQLite database, Ollama local models, and a scikit-learn Isolation Forest model. Feishu provides the user-facing message channel. The device handles three practical workflows: scheduled reminders, previous-day news summaries, and private document summaries.

## 2. System Design

The final architecture separates cloud messaging from local inference:

- Feishu outbound webhook: sends reminders, summaries, and alerts.
- Feishu inbound callback: receives text reminder commands and private document files.
- Local LLM: Ollama generates news and document summaries on the Raspberry Pi.
- Local rules path: deterministic summary fallback when Ollama is stopped or unavailable.
- Local anomaly model: Isolation Forest scores CPU, memory, disk, temperature, and network metrics.
- SQLite: stores tasks, task runs, inbound Feishu events, document summary metadata, and system metrics.

Current runtime service snapshot:

| Service | State |
| --- | --- |
| edge-task-hub.service | active |
| ollama.service | active |
| openclaw-gateway.service | inactive |

Current edge resource snapshot:

```text
total        used        free      shared  buff/cache   available
Mem:           7.6Gi       1.1Gi       1.4Gi       116Mi       5.4Gi       6.5Gi
Swap:          2.0Gi       253Mi       1.8Gi

Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2   29G   21G  6.9G  75% /
```

## 3. Edge AI Methods

### 3.1 Local LLM Summarization

The news and private document flows call Ollama through the local API at `127.0.0.1:11434`. The final summary model is `qwen3:1.7b`. The important policy change is that news summary is no longer treated as a strict 30-second live-demo task. A user can wait for a better daily summary, so the system uses a 300-second timeout for summary workflows.

The final verified qwen3:1.7b news-summary run used the real `/api/model/news-summary` API. It returned `backend=ollama`, `fallback=false`, `elapsed_seconds=55.624`, and `tokens_per_second=2.208`.

### 3.2 Deterministic Fallback

The rules path is intentionally kept. It is not a replacement for a local LLM, but it protects the edge workflow when the model service is stopped, the model is missing, RSS fails, or available memory is too low. This is an engineering decision: an edge device should expose failure and continue operating when possible.

### 3.3 Isolation Forest for Device Health

The Isolation Forest model is used for system monitoring, not for news text. It scores local metrics and provides fast anomaly detection without a cloud call. Current anomaly evidence reports `enabled=True`, `model_trained=True`, `samples_collected=3465`, and `anomalies_24h=15`.

### 3.4 Private Document Summaries

Private files sent through Feishu are downloaded to a temporary directory on the Raspberry Pi. Text is extracted locally from `.txt`, `.md`, `.docx`, and text-based `.pdf` files. The temporary file is deleted after processing, and the summary is generated locally with `qwen3:1.7b`. The original document text is not sent to a cloud model.

## 4. Experimental Setup

The evaluation used the Raspberry Pi deployment itself, not only a laptop simulation. The core services and configurations are:

- Device: Raspberry Pi running Linux and systemd user services.
- Application stack: FastAPI, Uvicorn, APScheduler, SQLAlchemy, SQLite, Jinja2 UI.
- AI stack: Ollama for local LLM inference and scikit-learn Isolation Forest for anomaly detection.
- Messaging stack: Feishu webhook for outbound messages and Feishu event callback for inbound commands/files.
- Candidate local models: qwen3:1.7b, qwen3:0.6b, qwen3.5:0.8b, qwen2.5:0.5b-instruct, tinyllama, llama3.2:1b.
- Router selected backend at generation time: ollama.
- Router selected model at generation time: qwen3:1.7b.

Standard scheduled tasks:

| Task | Type | Schedule | State |
| --- | --- | --- | --- |
| EdgeAI News Summary Demo | rss_digest | 0 8 * * * | enabled |
| Daily Previous-Day News Summary | rss_digest | 0 10 * * * | enabled |
| Lunch Reminder | reminder | 0 12 * * * | enabled |
| Sleep Reminder | reminder | 30 23 * * * | enabled |

## 5. Results

### 5.1 Model Comparison

| Candidate | Role | Decision | Latency | Speed | Evidence | Quality note |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3:1.7b | News and private document summaries | Selected | 55.624 s | 2.208 tokens/s | Real API run on the Raspberry Pi, backend=ollama, fallback=false. | Best final-summary choice because the project now allows waiting for quality instead of forcing a 30-second cold-start target. |
| qwen3:0.6b | Quick local chat and short reminder candidate | Kept as fast model | Configured fast path | Not the final news metric | Configured as OLLAMA_MODEL and listed in the resource-aware router. | Useful for short interactions, but the final daily news and private document flows prefer qwen3:1.7b quality. |
| qwen3.5:0.8b | News-summary candidate | Rejected | 74.832 s | 1.965 tokens/s | Cold-start benchmark returned an empty visible response before the current think=false handling. | Too slow and unstable for this project on the Raspberry Pi. |
| qwen2.5:0.5b-instruct | Legacy fast baseline | Rejected for final summaries | 14.345 s | 7.983 tokens/s | Fast historical benchmark, but output quality drifted and mistranslated Raspberry Pi in the news task. | Speed is good, but final project quality is weaker than qwen3:1.7b. |
| Rules fallback | Deterministic fallback | Kept | 0 s | N/A | Used when Ollama is stopped, too slow, or unavailable. | Not generative AI, but important for reliability on an edge device. |
| Isolation Forest | Device-health anomaly detection | Kept | Sub-second per sample | N/A | Runs locally on CPU, memory, disk, temperature, and network metrics. | Matches edge monitoring better than an LLM. |

### 5.2 Why qwen3.5:0.8b Timed Out for News Summary

The qwen3.5:0.8b result was not rejected only because it was newer or larger. It was rejected because its cold-start behavior was poor on this Raspberry Pi workload. Historical benchmark evidence recorded about 74.832 seconds, only 1.965 tokens per second, and an empty visible response. The most likely cause is a combination of cold model loading, slow generation on the Pi CPU, and Qwen-style internal thinking consuming the limited output budget before user-visible content. The runtime now sends `think=false`, but the final project still selects `qwen3:1.7b` because its quality is better for summaries when the user is allowed to wait.

### 5.3 Feishu Automation Results

| Validation item | Result |
| --- | --- |
| Feishu URL verification | Challenge response parser returns the exact challenge string. |
| Feishu text reminder | English commands create scheduled Task rows and register them with the scheduler. |
| Private document summary | .txt, .md, .docx, and text-based .pdf content is extracted locally before summarization. |
| News summary timeout policy | Slow but successful qwen3:1.7b output is accepted instead of falling back only because it exceeds 30 seconds. |
| Unit tests | 10 project tests pass on the Raspberry Pi. |
| English material scan | Source comments and generated documents are checked for non-English Chinese characters before submission. |

## 6. Discussion

The main result is a resource-aware Edge AI architecture. A single "best model" answer would be misleading. The best model depends on the job:

- `qwen3:1.7b` is the best final summary model among the tested local candidates because summary quality matters more than strict generation time.
- `qwen3:0.6b` remains useful for short local prompts and fast interactions.
- `qwen3.5:0.8b` is rejected for this Raspberry Pi news-summary workflow because it was slow and returned empty visible content.
- `qwen2.5:0.5b-instruct` is fast but produced weaker and less reliable summaries.
- Rules and Isolation Forest are kept because edge reliability is part of the project, not a fallback story to hide.

The privacy argument is also concrete. The device can receive a private file through Feishu, extract its text locally, summarize it with a local model, and send back only the summary. This is a better Edge AI story than uploading the document text to a cloud LLM.

## 7. Limitations

The system still has limitations:

- The Feishu inbound app must be configured with app id, app secret, verification token, allowlists, and a public callback URL before external use.
- Local LLM inference on Raspberry Pi remains slow, especially after cold starts.
- The current PDF extraction supports text-based PDFs; scanned PDFs would need OCR, which is not part of the final verified path.
- Model quality is evaluated with project-level evidence and manual inspection, not with a large benchmark dataset.
- Student names and IDs still need to be inserted before final Canvas submission.

## 8. Conclusion

Edge Task Hub demonstrates Edge AI by running useful intelligence directly on a Raspberry Pi: local LLM summaries, local private document processing, local anomaly detection, and local scheduling decisions. Feishu is used as the notification and command interface, but the privacy-sensitive inference work remains on the edge device. The final system is stronger after rejecting a strict 30-second summary policy: daily news and private document summaries can wait for the higher-quality `qwen3:1.7b` model, while shorter interactions and fallback paths remain available for reliability.

## References

[1] Ollama local model runtime, https://ollama.com

[2] FastAPI web framework, https://fastapi.tiangolo.com

[3] APScheduler documentation, https://apscheduler.readthedocs.io

[4] scikit-learn IsolationForest documentation, https://scikit-learn.org

[5] Raspberry Pi documentation, https://www.raspberrypi.com/documentation/
