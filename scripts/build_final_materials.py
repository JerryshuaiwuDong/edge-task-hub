#!/usr/bin/env python3
"""Build final English report, slides, and defense notes for Edge Task Hub."""

from __future__ import annotations

import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA = ROOT / "data"

REPORT_MD = DOCS / "final-report.md"
REPORT_HTML = DOCS / "final-report.html"
REPORT_PDF = DOCS / "final-report.pdf"
SLIDES_HTML = DOCS / "presentation-slides.html"
SLIDES_PDF = DOCS / "presentation-slides.pdf"
OUTLINE_MD = DOCS / "presentation-outline.md"
QA_MD = DOCS / "qa-prep.md"
CHECKLIST_MD = DOCS / "submission-checklist.md"
EVIDENCE_JSON = DOCS / "final-evidence.json"

LEGACY_REPORT_MD = DOCS / "edgeai-experiment-report.md"
LEGACY_REPORT_HTML = DOCS / "edgeai-experiment-report.html"
LEGACY_REPORT_PDF = DOCS / "edgeai-experiment-report.pdf"

BASE_URL = "http://127.0.0.1:8000"

FINAL_NEWS_EVIDENCE = {
    "timestamp": "2026-05-29",
    "scenario": "final_news_summary_api",
    "backend": "ollama",
    "model": "qwen3:1.7b",
    "ok": True,
    "fallback": False,
    "elapsed_seconds": 55.624,
    "tokens_per_second": 2.208,
    "note": "Verified through the real /api/model/news-summary endpoint after enabling think=false and a 300-second summary timeout.",
}

MODEL_ROWS = [
    {
        "candidate": "qwen3.5:2b",
        "role": "Large local LLM baseline",
        "decision": "Rejected before final inference",
        "elapsed": "Pull stalled and regressed",
        "speed": "N/A",
        "evidence": "Download attempts reached partial progress and then became unstable on the Pi, while the model blob increased storage pressure.",
        "quality": "A larger model may improve language quality, but it is not useful if the edge device cannot install and operate it reliably.",
        "constraint": "Storage and deployment stability",
    },
    {
        "candidate": "qwen3:1.7b",
        "role": "News and private document summaries",
        "decision": "Selected",
        "elapsed": "55.624 s",
        "speed": "2.208 tokens/s",
        "evidence": "Real API run on the Raspberry Pi, backend=ollama, fallback=false.",
        "quality": "Best final-summary choice because daily news and private document summaries can wait for better local output.",
        "constraint": "Quality-first local summarization",
    },
    {
        "candidate": "qwen3:0.6b",
        "role": "Quick local chat and short reminder candidate",
        "decision": "Kept as fast model",
        "elapsed": "Configured fast path",
        "speed": "Not the final news metric",
        "evidence": "Configured as OLLAMA_MODEL and listed in the resource-aware router.",
        "quality": "Useful for short interactions, but the final daily news and private document flows prefer qwen3:1.7b quality.",
        "constraint": "Low-latency lightweight prompts",
    },
    {
        "candidate": "qwen3.5:0.8b",
        "role": "Quantized Ollama summary candidate",
        "decision": "Rejected",
        "elapsed": "52-75 s",
        "speed": "about 2 tokens/s",
        "evidence": "Cold-start runs around 52.043 s to 74.832 s returned empty or length-limited visible output before the final policy.",
        "quality": "Quantization helped the model fit better than a 2B candidate, but cold-start latency and visible-output quality were still poor for this Pi workload.",
        "constraint": "Memory pressure and cold-start latency",
    },
    {
        "candidate": "qwen2.5:0.5b-instruct",
        "role": "Legacy fast baseline",
        "decision": "Rejected for final summaries",
        "elapsed": "14.345 s",
        "speed": "7.983 tokens/s",
        "evidence": "Fast historical benchmark, but output quality drifted and mistranslated Raspberry Pi in the news task.",
        "quality": "Speed is good, but final project quality is weaker than qwen3:1.7b.",
        "constraint": "Quality loss from very small LLM",
    },
    {
        "candidate": "Rules fallback",
        "role": "Program model for deterministic fallback",
        "decision": "Kept",
        "elapsed": "0 s",
        "speed": "N/A",
        "evidence": "Used when Ollama is stopped, too slow, or unavailable.",
        "quality": "Not a generative LLM, but a local program model keeps the edge workflow reliable and explainable.",
        "constraint": "Reliability under failure",
    },
    {
        "candidate": "Isolation Forest",
        "role": "Classical ML model for device health",
        "decision": "Kept",
        "elapsed": "Sub-second per sample",
        "speed": "N/A",
        "evidence": "Runs locally on CPU, memory, disk, temperature, and network metrics.",
        "quality": "A lightweight statistical model is a better fit than an LLM for edge resource monitoring.",
        "constraint": "Fast local metric scoring",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def command_output(cmd: list[str], timeout: int = 10) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return "not available"
    return (proc.stdout or proc.stderr).strip() or "not available"


def api_json(path: str, timeout: int = 5) -> dict[str, Any]:
    request = Request(f"{BASE_URL}{path}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (OSError, URLError):
        return {}
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def latest_record(records: list[dict[str, Any]], *, model: str | None = None, scenario: str | None = None) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for record in records:
        if model and record.get("model") == model:
            selected = record
        if scenario and record.get("scenario") == scenario:
            selected = record
    return selected


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    return {
        "timestamp": record.get("timestamp"),
        "scenario": record.get("scenario"),
        "backend": record.get("backend"),
        "model": record.get("model"),
        "ok": record.get("ok"),
        "elapsed_seconds": record.get("wall_seconds") or record.get("elapsed_seconds"),
        "tokens_per_second": record.get("eval_tokens_per_second") or record.get("tokens_per_second"),
        "fallback": record.get("fallback"),
        "feed_fallback": record.get("feed_fallback"),
        "decision": record.get("decision"),
    }


def query_tasks() -> list[dict[str, Any]]:
    db_path = DATA / "edge_task_hub.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select id, name, task_type, schedule_kind, cron_expr, timezone, enabled from tasks order by id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def collect_evidence() -> dict[str, Any]:
    model_status = api_json("/api/model/status", timeout=5)
    anomaly_stats = api_json("/api/anomaly/stats", timeout=5)
    system_snapshot = api_json("/api/system/snapshot", timeout=5)
    llm_benchmarks = load_jsonl(DATA / "llm_benchmarks.jsonl")
    model_comparison = load_jsonl(DATA / "model_comparison.jsonl")
    news_eval = load_jsonl(DATA / "news_summary_eval.jsonl")
    tasks = query_tasks()

    evidence = {
        "generated_at": now_iso(),
        "manual_final_news_run": FINAL_NEWS_EVIDENCE,
        "model_status": model_status,
        "anomaly_stats": anomaly_stats,
        "system_snapshot": system_snapshot,
        "service_status": {
            "edge_task_hub": command_output(["systemctl", "--user", "is-active", "edge-task-hub.service"]),
            "ollama": command_output(["systemctl", "is-active", "ollama.service"]),
            "openclaw_gateway": command_output(["systemctl", "--user", "is-active", "openclaw-gateway.service"]),
        },
        "resources": {
            "memory": command_output(["free", "-h"]),
            "disk": command_output(["df", "-h", "/"]),
        },
        "tasks": tasks,
        "historical_records": {
            "qwen35_08b": compact_record(latest_record(llm_benchmarks, model="qwen3.5:0.8b")),
            "qwen25_05b": compact_record(latest_record(llm_benchmarks, model="qwen2.5:0.5b-instruct")),
            "rules": compact_record(latest_record(model_comparison, scenario="rules")),
            "feed_fallback": compact_record(latest_record(model_comparison, scenario="feed_fallback")),
            "isolation_forest": compact_record(latest_record(model_comparison, scenario="isolation_forest")),
            "news_eval": [compact_record(record) for record in (news_eval[-3:] if len(news_eval) >= 3 else news_eval)],
        },
    }
    return evidence


def bullet(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(cell).replace("|", "/") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def task_table(tasks: list[dict[str, Any]]) -> str:
    selected = [
        task for task in tasks
        if task.get("name") in {
            "Daily Previous-Day News Summary",
            "Lunch Reminder",
            "Sleep Reminder",
            "EdgeAI News Summary Demo",
        }
    ]
    rows = [
        [
            task.get("name"),
            task.get("task_type"),
            task.get("cron_expr") or "one-time",
            "enabled" if task.get("enabled") else "disabled",
        ]
        for task in selected
    ]
    if not rows:
        rows = [["Task database not available", "-", "-", "-"]]
    return md_table(["Task", "Type", "Schedule", "State"], rows)


def model_table() -> str:
    return md_table(
        ["Candidate", "Role", "Decision", "Latency", "Speed", "Edge constraint", "Quality note"],
        [
            [
                row["candidate"],
                row["role"],
                row["decision"],
                row["elapsed"],
                row["speed"],
                row["constraint"],
                row["quality"],
            ]
            for row in MODEL_ROWS
        ],
    )


def model_decision_table() -> str:
    return md_table(
        ["Candidate", "Constraint exposed", "Evidence", "Decision"],
        [
            [row["candidate"], row["constraint"], row["evidence"], row["decision"]]
            for row in MODEL_ROWS
        ],
    )


def final_stack_table() -> str:
    return md_table(
        ["Local intelligence", "Job", "Why this belongs on the edge"],
        [
            ["qwen3:1.7b", "Daily news and private document summaries", "Quality matters more than strict live latency, and private text stays on the Pi."],
            ["qwen3:0.6b", "Short local prompts and quick interactions", "Small enough for lower-latency edge interaction when a long summary is not needed."],
            ["Rules fallback", "RSS failure, missing model, or unavailable Ollama", "Deterministic local behavior keeps the user workflow alive and auditable."],
            ["Isolation Forest", "CPU, memory, disk, temperature, and network anomaly detection", "A compact program model scores device health locally without cloud inference."],
            ["APScheduler plus SQLite", "Reminder creation and execution", "The device owns the schedule and can remind through Feishu at the right time."],
        ],
    )


def build_report(evidence: dict[str, Any]) -> str:
    service = evidence["service_status"]
    resources = evidence["resources"]
    anomaly = evidence.get("anomaly_stats") or {}
    model_status = evidence.get("model_status") or {}
    candidates = ", ".join(model_status.get("candidate_models") or ["qwen3:1.7b", "qwen3:0.6b", "qwen3.5:0.8b", "qwen2.5:0.5b-instruct"])
    router = (model_status.get("router") or {})
    selected_backend = router.get("selected_backend") or "ollama/rules depending on local state"
    selected_model = router.get("selected_model") or "qwen3:1.7b for quality summaries"

    validation_rows = md_table(
        ["Validation item", "Result"],
        [
            ["Feishu URL verification", "Challenge response parser returns the exact challenge string."],
            ["Feishu text reminder", "English commands create scheduled Task rows and register them with the scheduler."],
            ["Private document summary", ".txt, .md, .docx, and text-based .pdf content is extracted locally before summarization."],
            ["News summary timeout policy", "Slow but successful qwen3:1.7b output is accepted instead of falling back only because it exceeds 30 seconds."],
            ["Unit tests", "10 project tests pass on the Raspberry Pi."],
            ["English material scan", "Source comments and generated documents are checked for non-English Chinese characters before submission."],
        ],
    )

    md = f"""# Edge Task Hub: Resource-Aware Edge AI Automation on Raspberry Pi

Authors: to be added before submission

Generated: {evidence['generated_at']}

## Abstract

This paper presents Edge Task Hub, a Raspberry Pi based Edge AI system for scheduled reminders, daily news summaries, private document summaries, and device-health monitoring. The main research question is not "which LLM is newest"; it is "which local intelligence can run reliably on a small edge device while keeping private data local." We tested a larger 2B-size Qwen candidate, quantized Ollama models, a very small fast model, deterministic program rules, and a classical Isolation Forest model. The final design selects `qwen3:1.7b` for quality-first news and document summaries, keeps `qwen3:0.6b` for short prompts, rejects `qwen3.5:0.8b` for this Pi workload because of cold-start latency and empty or length-limited output, and keeps rules plus Isolation Forest because Edge AI also needs reliability and device awareness.

## 1. Introduction

This project was built for an Edge AI course, so the important contribution must be the edge design. A normal cloud chatbot can call a large remote model and ignore memory, storage, cold start, and privacy. Edge Task Hub does the opposite. It uses a Raspberry Pi as the decision point, runs local models when possible, records failures, and sends only finished results through Feishu.

The first version of the idea was simple: run a local model to summarize news and send reminders. That was not enough for a strong Edge AI defense. A Raspberry Pi is not a cloud GPU server. It has limited RAM, limited SD-card storage, slow cold starts, and a user who still expects the system to remind them even if a model is unavailable. The project therefore evolved from "use an LLM" into "choose the right local model or program model for each edge job."

The system now supports three user workflows. It creates scheduled reminders through Feishu text commands, generates a previous-day news summary each morning, and summarizes private files sent through Feishu. It also monitors its own CPU, memory, disk, temperature, and network metrics with a local anomaly model.

The paper focuses on experimental setup, results, and analysis, as required by the presentation instructions. Background is kept short because the course requirement is to defend the Edge AI part.

## 2. Edge AI Requirements

The system was designed around five edge requirements:

{bullet([
    "Privacy: private document text should be processed on the Raspberry Pi, not uploaded to a cloud LLM.",
    "Memory: model selection must respect the actual RAM pressure of the device.",
    "Storage: a model that cannot be installed cleanly on the SD card is not a usable edge model.",
    "Latency policy: reminders need punctual delivery, but daily news and private document summaries can wait for better quality.",
    "Reliability: when an LLM fails, the device should expose the failure and still provide deterministic behavior when possible.",
])}

These requirements explain why the final project uses more than one model. Edge AI is not only about a large neural model. It is about local decision making under device constraints. In this project, LLMs handle language, program rules handle deterministic fallback, and Isolation Forest handles device health.

## 3. System Architecture

The final architecture separates cloud messaging from local inference. Feishu is the user interface. The Raspberry Pi is the intelligence boundary.

{final_stack_table()}

Current runtime service snapshot:

{md_table(["Service", "State"], [["edge-task-hub.service", service.get("edge_task_hub")], ["ollama.service", service.get("ollama")], ["openclaw-gateway.service", service.get("openclaw_gateway")]])}

Current edge resource snapshot:

```text
{resources.get("memory")}

{resources.get("disk")}
```

The core software stack is FastAPI, APScheduler, SQLite, Ollama, and scikit-learn. FastAPI exposes the local service and Feishu callback endpoints. APScheduler owns the reminder and summary timing. SQLite records tasks, runs, events, document summary metadata, and system metrics. Ollama runs local language models. Isolation Forest scores system-health metrics.

## 4. Experimental Setup

The evaluation used the deployed Raspberry Pi instead of only a laptop simulation. This matters because model behavior on the Pi is dominated by real edge limits: RAM, SD-card space, CPU speed, and cold model loading.

The tested intelligence options were:

{bullet([
    "A larger 2B-size Qwen candidate, used to test whether a stronger LLM was practical on this edge device.",
    "`qwen3.5:0.8b`, a quantized Ollama candidate expected to fit better than the 2B-size model.",
    "`qwen2.5:0.5b-instruct`, a very small fast baseline.",
    "`qwen3:1.7b`, the final quality-first model for summary workflows.",
    "`qwen3:0.6b`, a lightweight model kept for quick prompts.",
    "Rules, a deterministic program model used when generative inference is unavailable.",
    "Isolation Forest, a classical local ML model used for device-health anomaly detection.",
])}

Application and runtime setup:

{bullet([
    "Device: Raspberry Pi running Linux and systemd user services.",
    "Application stack: FastAPI, Uvicorn, APScheduler, SQLAlchemy, SQLite, and Jinja2 UI.",
    "AI stack: Ollama for local LLM inference and scikit-learn Isolation Forest for anomaly detection.",
    "Messaging stack: Feishu webhook for outbound messages and Feishu event callback for inbound commands and files.",
    f"Candidate local models visible to the router: {candidates}.",
    f"Router selected backend at report generation time: {selected_backend}.",
    f"Router selected model at report generation time: {selected_model}.",
])}

Standard scheduled tasks:

{task_table(evidence.get("tasks") or [])}

## 5. Results

### 5.1 Model Exploration Logic

The model exploration followed a practical edge sequence. First, we tried to move toward a larger model because larger LLMs usually preserve facts and produce better summaries. The 2B-size candidate exposed the first edge problem: the Pi did not only need enough theoretical RAM, it also needed stable download, storage, and startup behavior. A model that is too hard to install is not a valid edge deployment choice.

Second, we tested a quantized Ollama model, `qwen3.5:0.8b`. Quantization is important for Edge AI because it reduces model size and memory pressure. However, the benchmark still showed about 52 to 75 seconds of cold-start generation at about 2 tokens per second, with empty or length-limited visible output. This means quantization improved deployability but did not fully solve cold-start and output-quality problems.

Third, we tested `qwen2.5:0.5b-instruct`. It was much faster, with a recorded 14.345-second run at 7.983 tokens per second, but summary quality was weaker and included semantic drift. This showed the opposite edge failure: a model can fit the device and still be too weak for the user-facing task.

Finally, we changed the policy. News summary is not a strict real-time generation task. The user wants a useful previous-day summary at 10:00, and the system can wait for better output. The final system therefore selects `qwen3:1.7b` for daily news and private document summaries, while keeping `qwen3:0.6b` for shorter interactions.

### 5.2 Model Results

{model_decision_table()}

### 5.3 Final News Summary Result

The final verified `qwen3:1.7b` news-summary run used the real `/api/model/news-summary` endpoint on the Raspberry Pi. It returned `backend=ollama`, `fallback=false`, `elapsed_seconds=55.624`, and `tokens_per_second=2.208`.

This is not the fastest result, but it is the right result for the chosen edge workflow. Daily news summaries and private document summaries are allowed to wait. A strict short timeout would make the system look faster in a demo but would reduce summary quality and hide the real edge tradeoff.

### 5.4 Why `qwen3.5:0.8b` Cold-Started Too Slowly

The `qwen3.5:0.8b` issue is an important Edge AI lesson. A quantized model is smaller, but it is not automatically better for every edge workload. The recorded cold-start runs took about 52.043 seconds to 74.832 seconds, produced about 2 tokens per second, and returned empty or length-limited visible output in the news-summary style task.

The likely causes are combined:

{bullet([
    "Cold loading: the model must be loaded into memory before useful generation starts.",
    "CPU generation speed: the Raspberry Pi CPU produces tokens slowly compared with a GPU or cloud service.",
    "Output-budget behavior: Qwen-style thinking can consume tokens before user-visible summary content appears.",
    "Memory pressure: one benchmark showed available memory dropping significantly during the run, which is exactly the kind of constraint an edge system must respect.",
])}

The runtime now uses `think=false` for Qwen-style models, but the final design still rejects this model for daily news summaries because the project has a better fit: `qwen3:1.7b` for waitable quality output and `qwen3:0.6b` for fast short prompts.

### 5.5 Feishu Automation Results

{validation_rows}

### 5.6 Local Device-Health Model

The Isolation Forest model is not a language model, but it is still part of the Edge AI design. It runs locally on system metrics and detects abnormal device behavior. Current anomaly evidence reports `enabled={anomaly.get('enabled', 'unknown')}`, `model_trained={anomaly.get('model_trained', 'unknown')}`, `samples_collected={anomaly.get('samples_collected', 'unknown')}`, and `anomalies_24h={anomaly.get('anomalies_24h', 'unknown')}`.

This is why the report describes both "large models" and "program models." Edge AI should choose the smallest reliable intelligence for the job. An LLM is useful for language summaries. Rules are useful for deterministic fallback. Isolation Forest is useful for numeric resource monitoring.

## 6. Discussion and Analysis

The main result is a resource-aware Edge AI architecture. A single "best model" answer would be misleading because edge devices are constrained. The best model depends on the job:

{bullet([
    "For private documents and daily news, quality is more important than strict generation time, so `qwen3:1.7b` is selected.",
    "For short interactions, a smaller model such as `qwen3:0.6b` is more suitable.",
    "For failure cases, rules are more predictable than forcing a slow or missing LLM.",
    "For device health, Isolation Forest is more efficient and explainable than asking a language model to inspect numeric metrics.",
])}

The privacy argument is concrete. A user can send a private Word file or text file through Feishu. The Pi downloads it to a temporary directory, extracts text locally, summarizes it with the local model, removes the temporary file, and sends back only the summary. The sensitive document text is not sent to a cloud model.

The reminder argument is also concrete. Built-in tasks can remind the user to eat at 12:00 and sleep at 23:30, and Feishu text commands can create new reminders. The timing decision belongs to the edge device. Feishu only delivers the message.

## 7. Limitations and Future Work

The system still has limitations:

{bullet([
    "The Feishu inbound app must be configured with app id, app secret, verification token, allowlists, and a public callback URL before external use.",
    "Local LLM inference on Raspberry Pi remains slow, especially after cold starts.",
    "The current PDF extraction supports text-based PDFs; scanned PDFs would need OCR, which is not part of the final verified path.",
    "Model quality is evaluated with project-level evidence and manual inspection, not with a large benchmark dataset.",
    "Student names and IDs still need to be inserted before final Canvas submission.",
])}

Future work should add a more formal quality rubric for summaries, test more quantized models under the same input, and add OCR for scanned documents if the device can handle the extra CPU cost.

## 8. Conclusion

Edge Task Hub demonstrates Edge AI by running useful intelligence directly on a Raspberry Pi: local LLM summaries, local private document processing, local anomaly detection, local reminder scheduling, and local fallback decisions. The model exploration matters because it shows the edge tradeoff step by step. A larger model was not deployable enough, a quantized model still cold-started poorly, a very small model was fast but lower quality, and the final system chose a hybrid model stack instead of pretending one model solves every problem.

The final defense is simple: Feishu is the communication channel, but the private processing and decisions stay on the edge device. That is the Edge AI contribution.

## References

[1] Ollama local model runtime, https://ollama.com

[2] FastAPI web framework, https://fastapi.tiangolo.com

[3] APScheduler documentation, https://apscheduler.readthedocs.io

[4] scikit-learn IsolationForest documentation, https://scikit-learn.org

[5] Raspberry Pi documentation, https://www.raspberrypi.com/documentation/
"""
    return md


def escape_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def html_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape_inline(str(h))}</th>" for h in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{escape_inline(str(cell))}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def markdown_to_html(markdown: str, *, title: str, slides: bool = False) -> str:
    lines = markdown.splitlines()
    parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    table_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            parts.append("<p>" + escape_inline(" ".join(paragraph)) + "</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            parts.append("<ul>" + "".join(f"<li>{escape_inline(item)}</li>" for item in list_items) + "</ul>")
            list_items = []

    def flush_table() -> None:
        nonlocal table_lines
        if len(table_lines) >= 2:
            rows: list[list[str]] = []
            for line in table_lines:
                if re.match(r"^\|\s*-", line):
                    continue
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                rows.append(cells)
            if rows:
                parts.append(html_table(rows[0], rows[1:]))
        table_lines = []

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            flush_table()
            if in_code:
                parts.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")
                in_code = False
                code_lines = []
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("|"):
            flush_paragraph()
            flush_list()
            table_lines.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        if line.startswith("# "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h1>{escape_inline(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h2>{escape_inline(line[3:].strip())}</h2>")
        elif line.startswith("### "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h3>{escape_inline(line[4:].strip())}</h3>")
        elif line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:].strip())
        else:
            paragraph.append(line.strip())

    flush_paragraph()
    flush_list()
    flush_table()
    if in_code:
        parts.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")

    css = report_css()
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{css}</style></head><body>"
        + "\n".join(parts)
        + "</body></html>"
    )


def report_css() -> str:
    return """
    @page { size: A4; margin: 16mm; }
    body { font-family: Arial, Helvetica, sans-serif; color: #1f2933; line-height: 1.42; font-size: 10.4pt; margin: 0; }
    h1 { font-size: 23pt; line-height: 1.12; color: #102a43; margin: 0 0 10px; page-break-after: avoid; }
    h2 { font-size: 14pt; color: #243b53; border-bottom: 1px solid #bcccdc; padding-bottom: 4px; margin-top: 20px; page-break-after: avoid; }
    h3 { font-size: 11.5pt; color: #334e68; margin-top: 14px; page-break-after: avoid; }
    p { margin: 6px 0; }
    ul { margin-top: 5px; padding-left: 18px; }
    li { margin: 2px 0; }
    table { width: 100%; border-collapse: collapse; margin: 9px 0 12px; font-size: 8.1pt; page-break-inside: avoid; }
    th { background: #edf2f7; color: #102a43; text-align: left; }
    th, td { border: 1px solid #cbd5e1; padding: 4px 5px; vertical-align: top; }
    pre { background: #f8fafc; border: 1px solid #cbd5e1; padding: 8px; font-size: 8pt; white-space: pre-wrap; }
    code { font-family: Consolas, Menlo, monospace; font-size: 92%; }
    """


def reportlab_inline(text: str) -> str:
    pieces: list[str] = []
    pos = 0
    for match in re.finditer(r"`([^`]+)`", text):
        pieces.append(html.escape(text[pos:match.start()]))
        pieces.append(f"<font name='Courier'>{html.escape(match.group(1))}</font>")
        pos = match.end()
    pieces.append(html.escape(text[pos:]))
    marked = "".join(pieces)
    marked = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", marked)
    return marked


def reportlab_pdf(markdown: str, pdf_path: Path) -> bool:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        return False

    if pdf_path.exists():
        pdf_path.unlink()

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Edge Task Hub Final Report",
        author="Edge Task Hub Team",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=colors.HexColor("#123047"),
            alignment=TA_CENTER,
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverSub",
            parent=styles["Normal"],
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#40566d"),
            alignment=TA_CENTER,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.6,
            leading=13.2,
            textColor=colors.HexColor("#1d2935"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportH2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13.2,
            leading=16,
            textColor=colors.HexColor("#17324d"),
            spaceBefore=11,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportH3",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.8,
            leading=13,
            textColor=colors.HexColor("#28445f"),
            spaceBefore=8,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletText",
            parent=styles["Normal"],
            leftIndent=11,
            firstLineIndent=-7,
            fontSize=9.4,
            leading=12.8,
            textColor=colors.HexColor("#1d2935"),
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            parent=styles["Normal"],
            fontSize=7.4,
            leading=9.2,
            textColor=colors.HexColor("#1d2935"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9.2,
            textColor=colors.HexColor("#102a43"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="CodeBlock",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#1f2933"),
        )
    )

    story: list[Any] = []
    lines = markdown.splitlines()
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("# ") else "Edge Task Hub Final Report"
    generated = next((line for line in lines if line.startswith("Generated:")), "Generated: unknown")
    story.append(Spacer(1, 38 * mm))
    story.append(Paragraph(reportlab_inline(title), styles["CoverTitle"]))
    story.append(Paragraph("Resource-Aware Edge AI Automation on Raspberry Pi", styles["CoverSub"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("Authors and student IDs: to be added before submission", styles["CoverSub"]))
    story.append(Paragraph(reportlab_inline(generated), styles["CoverSub"]))
    story.append(Spacer(1, 22 * mm))
    story.append(
        Table(
            [[Paragraph("Feishu is the message channel. The Raspberry Pi is the privacy and inference boundary.", styles["ReportBody"])]],
            colWidths=[doc.width],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef5f8")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#7aa3b3")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        )
    )
    story.append(PageBreak())

    paragraph: list[str] = []
    list_items: list[str] = []
    table_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def table_widths(columns: int) -> list[float]:
        if columns == 2:
            return [doc.width * 0.28, doc.width * 0.72]
        if columns == 3:
            return [doc.width * 0.24, doc.width * 0.34, doc.width * 0.42]
        if columns == 4:
            return [doc.width * 0.18, doc.width * 0.24, doc.width * 0.40, doc.width * 0.18]
        if columns == 5:
            return [doc.width * 0.18, doc.width * 0.18, doc.width * 0.18, doc.width * 0.23, doc.width * 0.23]
        return [doc.width / columns for _ in range(columns)]

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            story.append(Paragraph(reportlab_inline(" ".join(paragraph)), styles["ReportBody"]))
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        for item in list_items:
            story.append(Paragraph("- " + reportlab_inline(item), styles["BulletText"]))
        list_items = []

    def flush_table() -> None:
        nonlocal table_lines
        if len(table_lines) < 2:
            table_lines = []
            return
        rows: list[list[str]] = []
        for raw in table_lines:
            if re.match(r"^\|\s*-", raw):
                continue
            rows.append([cell.strip() for cell in raw.strip("|").split("|")])
        table_lines = []
        if not rows:
            return
        formatted = []
        for row_index, row in enumerate(rows):
            style_name = "TableHeader" if row_index == 0 else "TableCell"
            formatted.append([Paragraph(reportlab_inline(cell), styles[style_name]) for cell in row])
        table = Table(formatted, colWidths=table_widths(len(rows[0])), repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef4")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#bac7d5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 5))

    started_body = False
    for line in lines:
        if line.startswith("# "):
            started_body = True
            continue
        if not started_body:
            continue
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            flush_table()
            if in_code:
                story.append(
                    Table(
                        [[Paragraph(html.escape("\n".join(code_lines)).replace("\n", "<br/>"), styles["CodeBlock"])]],
                        colWidths=[doc.width],
                        style=TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f8fa")),
                                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5df")),
                                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                ("TOPPADDING", (0, 0), (-1, -1), 6),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ]
                        ),
                    )
                )
                story.append(Spacer(1, 5))
                in_code = False
                code_lines = []
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("|"):
            flush_paragraph()
            flush_list()
            table_lines.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_list()
            story.append(Paragraph(reportlab_inline(line[3:].strip()), styles["ReportH2"]))
        elif line.startswith("### "):
            flush_paragraph()
            flush_list()
            story.append(Paragraph(reportlab_inline(line[4:].strip()), styles["ReportH3"]))
        elif line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:].strip())
        elif line.startswith("Authors:") or line.startswith("Generated:"):
            continue
        else:
            paragraph.append(line.strip())

    flush_paragraph()
    flush_list()
    flush_table()

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(document.leftMargin, 9 * mm, "Edge Task Hub - Edge AI Final Report")
        canvas.drawRightString(A4[0] - document.rightMargin, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return pdf_path.exists() and pdf_path.stat().st_size > 1024


def slides_reportlab_pdf(slides: list[dict[str, Any]], pdf_path: Path) -> bool:
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.pdfgen import canvas
        from reportlab.platypus import Paragraph, Table, TableStyle
    except ImportError:
        return False

    if pdf_path.exists():
        pdf_path.unlink()

    width, height = 13.333 * inch, 7.5 * inch
    margin_x = 0.58 * inch
    top_margin = 0.42 * inch
    palette = [colors.HexColor("#2f6f5e"), colors.HexColor("#315c9c"), colors.HexColor("#b45f3c")]
    secondary = colors.HexColor("#d69f40")
    text_color = colors.HexColor("#172033")
    muted = colors.HexColor("#52647a")
    pale = colors.HexColor("#eef4f6")
    bg = colors.HexColor("#f7f9fc")
    ink = colors.HexColor("#0f172a")
    line = colors.HexColor("#b8c6d6")

    def wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if stringWidth(candidate, font, size) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def draw_wrapped(c: Any, text: str, x: float, y: float, font: str, size: float, leading: float, max_width: float, fill: Any) -> float:
        c.setFont(font, size)
        c.setFillColor(fill)
        for line in wrap_text(text, font, size, max_width):
            c.drawString(x, y, line)
            y -= leading
        return y

    def paragraph(text: str, size: float, bold: bool = False) -> Paragraph:
        return Paragraph(
            reportlab_inline(str(text)),
            ParagraphStyle(
                name=f"SlideCell{size}{bold}",
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=size,
                leading=size + 3,
                textColor=text_color,
            ),
        )

    def draw_panel(c: Any, x: float, y: float, w: float, h: float, *, fill: Any | None = None, stroke: Any | None = None, radius: float = 10) -> None:
        c.setFillColor(fill or colors.white)
        c.setStrokeColor(stroke or line)
        c.setLineWidth(1)
        c.roundRect(x, y, w, h, radius, stroke=1, fill=1)

    def draw_label(c: Any, text: str, x: float, y: float, *, color: Any = muted, size: float = 9, bold: bool = True) -> None:
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y, text)

    def draw_centered(c: Any, text: str, x: float, y: float, w: float, *, color: Any = text_color, size: float = 11, bold: bool = True) -> None:
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawCentredString(x + w / 2, y, text)

    def draw_arrow(c: Any, x1: float, y1: float, x2: float, y2: float, color: Any = line) -> None:
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(2)
        c.line(x1, y1, x2, y2)
        dx = x2 - x1
        dy = y2 - y1
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        size = 7
        c.line(x2, y2, x2 - ux * size + px * size * 0.55, y2 - uy * size + py * size * 0.55)
        c.line(x2, y2, x2 - ux * size - px * size * 0.55, y2 - uy * size - py * size * 0.55)

    def draw_icon(c: Any, kind: str, x: float, y: float, s: float, color: Any) -> None:
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(2)
        if kind == "pi":
            c.roundRect(x, y, s, s, 8, stroke=1, fill=0)
            c.setFont("Helvetica-Bold", s * 0.34)
            c.drawCentredString(x + s / 2, y + s * 0.38, "Pi")
            for i in range(4):
                c.circle(x + s * 0.18 + i * s * 0.21, y + s * 0.82, 2.2, stroke=0, fill=1)
        elif kind == "cloud":
            c.circle(x + s * 0.36, y + s * 0.48, s * 0.20, stroke=1, fill=0)
            c.circle(x + s * 0.52, y + s * 0.56, s * 0.25, stroke=1, fill=0)
            c.circle(x + s * 0.68, y + s * 0.47, s * 0.18, stroke=1, fill=0)
            c.line(x + s * 0.22, y + s * 0.36, x + s * 0.78, y + s * 0.36)
        elif kind == "message":
            c.roundRect(x + s * 0.1, y + s * 0.25, s * 0.8, s * 0.5, 8, stroke=1, fill=0)
            c.line(x + s * 0.28, y + s * 0.25, x + s * 0.20, y + s * 0.08)
            c.circle(x + s * 0.34, y + s * 0.50, 2, stroke=0, fill=1)
            c.circle(x + s * 0.50, y + s * 0.50, 2, stroke=0, fill=1)
            c.circle(x + s * 0.66, y + s * 0.50, 2, stroke=0, fill=1)
        elif kind == "lock":
            c.roundRect(x + s * 0.22, y + s * 0.20, s * 0.56, s * 0.45, 5, stroke=1, fill=0)
            c.arc(x + s * 0.31, y + s * 0.44, x + s * 0.69, y + s * 0.88, 0, 180)
            c.circle(x + s * 0.50, y + s * 0.43, 2.2, stroke=0, fill=1)
        elif kind == "cpu":
            c.roundRect(x + s * 0.22, y + s * 0.22, s * 0.56, s * 0.56, 4, stroke=1, fill=0)
            c.roundRect(x + s * 0.35, y + s * 0.35, s * 0.30, s * 0.30, 3, stroke=1, fill=0)
            for i in range(4):
                p = x + s * (0.28 + i * 0.15)
                c.line(p, y + s * 0.14, p, y + s * 0.22)
                c.line(p, y + s * 0.78, p, y + s * 0.86)
                q = y + s * (0.28 + i * 0.15)
                c.line(x + s * 0.14, q, x + s * 0.22, q)
                c.line(x + s * 0.78, q, x + s * 0.86, q)
        elif kind == "clock":
            c.circle(x + s * 0.5, y + s * 0.5, s * 0.34, stroke=1, fill=0)
            c.line(x + s * 0.5, y + s * 0.5, x + s * 0.5, y + s * 0.72)
            c.line(x + s * 0.5, y + s * 0.5, x + s * 0.66, y + s * 0.42)
        elif kind == "db":
            c.ellipse(x + s * 0.20, y + s * 0.63, x + s * 0.80, y + s * 0.83, stroke=1, fill=0)
            c.line(x + s * 0.20, y + s * 0.30, x + s * 0.20, y + s * 0.73)
            c.line(x + s * 0.80, y + s * 0.30, x + s * 0.80, y + s * 0.73)
            c.ellipse(x + s * 0.20, y + s * 0.20, x + s * 0.80, y + s * 0.40, stroke=1, fill=0)
            c.ellipse(x + s * 0.20, y + s * 0.41, x + s * 0.80, y + s * 0.61, stroke=1, fill=0)
        elif kind == "brain":
            pts = [(0.25, 0.42), (0.34, 0.65), (0.50, 0.74), (0.68, 0.64), (0.75, 0.42), (0.62, 0.28), (0.43, 0.30)]
            last = None
            for px, py in pts:
                cx, cy = x + px * s, y + py * s
                c.circle(cx, cy, s * 0.055, stroke=1, fill=0)
                if last:
                    c.line(last[0], last[1], cx, cy)
                last = (cx, cy)
        elif kind == "doc":
            c.rect(x + s * 0.25, y + s * 0.16, s * 0.50, s * 0.68, stroke=1, fill=0)
            c.line(x + s * 0.36, y + s * 0.62, x + s * 0.64, y + s * 0.62)
            c.line(x + s * 0.36, y + s * 0.50, x + s * 0.64, y + s * 0.50)
            c.line(x + s * 0.36, y + s * 0.38, x + s * 0.58, y + s * 0.38)
        elif kind == "shield":
            path = c.beginPath()
            path.moveTo(x + s * 0.50, y + s * 0.85)
            path.lineTo(x + s * 0.78, y + s * 0.70)
            path.lineTo(x + s * 0.70, y + s * 0.33)
            path.lineTo(x + s * 0.50, y + s * 0.16)
            path.lineTo(x + s * 0.30, y + s * 0.33)
            path.lineTo(x + s * 0.22, y + s * 0.70)
            path.close()
            c.drawPath(path, stroke=1, fill=0)
        elif kind == "check":
            c.circle(x + s * 0.5, y + s * 0.5, s * 0.32, stroke=1, fill=0)
            c.line(x + s * 0.34, y + s * 0.50, x + s * 0.46, y + s * 0.38)
            c.line(x + s * 0.46, y + s * 0.38, x + s * 0.68, y + s * 0.62)
        else:
            c.circle(x + s * 0.5, y + s * 0.5, s * 0.32, stroke=1, fill=0)

    def icon_card(c: Any, x: float, y: float, w: float, h: float, icon: str, title: str, note: str, accent: Any) -> None:
        draw_panel(c, x, y, w, h, fill=colors.white, stroke=line, radius=12)
        draw_icon(c, icon, x + 10, y + h - 50, 36, accent)
        draw_label(c, title, x + 56, y + h - 28, color=ink, size=12)
        c.setFillColor(muted)
        c.setFont("Helvetica", 8.8)
        for i, text_line in enumerate(wrap_text(note, "Helvetica", 8.8, w - 66)[:2]):
            c.drawString(x + 56, y + h - 44 - i * 11, text_line)

    def draw_visual(c: Any, kind: str | None, x: float, y: float, w: float, h: float, accent: Any) -> None:
        if not kind:
            return
        draw_panel(c, x, y, w, h, fill=colors.white, stroke=line, radius=18)
        pad = 18
        inner_x, inner_y = x + pad, y + pad
        inner_w, inner_h = w - 2 * pad, h - 2 * pad
        if kind == "hero":
            cx, cy = x + w * 0.52, y + h * 0.55
            c.setFillColor(pale)
            c.setStrokeColor(accent)
            c.circle(cx, cy, 78, stroke=1, fill=1)
            draw_icon(c, "pi", cx - 34, cy - 34, 68, accent)
            nodes = [
                ("message", "Feishu", x + 34, y + h - 86),
                ("brain", "Inference", x + w - 150, y + h - 86),
                ("clock", "Schedule", x + 38, y + 42),
                ("shield", "Private", x + w - 150, y + 42),
            ]
            for icon, label, nx, ny in nodes:
                draw_panel(c, nx, ny, 116, 58, fill=colors.HexColor("#f8fbfd"), stroke=line, radius=14)
                draw_icon(c, icon, nx + 8, ny + 11, 35, accent)
                draw_label(c, label, nx + 48, ny + 31, color=ink, size=11)
                draw_arrow(c, nx + 58, ny + 29, cx, cy, accent)
        elif kind == "proof":
            labels = [("Setup", "real Pi runtime", "cpu"), ("Results", "measured tradeoffs", "check"), ("Analysis", "edge constraints", "shield")]
            card_w = (inner_w - 24) / 3
            for i, (title, note, icon) in enumerate(labels):
                icon_card(c, inner_x + i * (card_w + 12), inner_y + inner_h * 0.42, card_w, inner_h * 0.42, icon, title, note, accent)
            c.setStrokeColor(accent)
            c.setLineWidth(3)
            c.line(inner_x + 8, inner_y + inner_h * 0.28, inner_x + inner_w - 8, inner_y + inner_h * 0.28)
            draw_label(c, "Course target: defend the EDGE part of AI", inner_x + 10, inner_y + inner_h * 0.18, color=accent, size=14)
        elif kind == "constraints":
            items = [("lock", "Privacy"), ("cpu", "Memory"), ("db", "Storage"), ("clock", "Latency"), ("shield", "Reliability")]
            for i, (icon, label) in enumerate(items):
                angle_x = inner_x + (i % 3) * (inner_w / 3)
                angle_y = inner_y + inner_h * (0.55 if i < 3 else 0.18)
                icon_card(c, angle_x + 6, angle_y, inner_w / 3 - 12, 82, icon, label, "edge constraint", accent if i % 2 == 0 else secondary)
        elif kind == "architecture":
            left = inner_x
            mid = inner_x + inner_w * 0.34
            right = inner_x + inner_w * 0.70
            icon_card(c, left, inner_y + inner_h * 0.58, 145, 80, "message", "Feishu", "commands and results", accent)
            draw_panel(c, mid, inner_y + 16, inner_w * 0.31, inner_h - 32, fill=colors.HexColor("#eef5f8"), stroke=accent, radius=16)
            draw_centered(c, "Raspberry Pi", mid, inner_y + inner_h - 46, inner_w * 0.31, color=accent, size=14)
            for j, (icon, label) in enumerate([("cpu", "FastAPI"), ("clock", "Scheduler"), ("db", "SQLite"), ("brain", "Ollama"), ("shield", "Isolation Forest")]):
                draw_icon(c, icon, mid + 16, inner_y + inner_h - 88 - j * 36, 24, accent)
                draw_label(c, label, mid + 48, inner_y + inner_h - 73 - j * 36, color=ink, size=10)
            icon_card(c, right, inner_y + inner_h * 0.58, 155, 80, "doc", "Summaries", "news and documents", secondary)
            icon_card(c, right, inner_y + inner_h * 0.22, 155, 80, "clock", "Reminders", "local timing", secondary)
            draw_arrow(c, left + 150, inner_y + inner_h * 0.68, mid - 10, inner_y + inner_h * 0.68, accent)
            draw_arrow(c, mid + inner_w * 0.31 + 8, inner_y + inner_h * 0.68, right - 10, inner_y + inner_h * 0.68, accent)
            draw_arrow(c, mid + inner_w * 0.31 + 8, inner_y + inner_h * 0.32, right - 10, inner_y + inner_h * 0.32, accent)
        elif kind == "workflows":
            events = [("10:00", "News", "doc"), ("12:00", "Lunch", "clock"), ("23:30", "Sleep", "clock"), ("Anytime", "File summary", "lock")]
            yline = inner_y + inner_h * 0.54
            c.setStrokeColor(accent)
            c.setLineWidth(3)
            c.line(inner_x + 30, yline, inner_x + inner_w - 30, yline)
            gap = (inner_w - 80) / (len(events) - 1)
            for i, (time, title, icon) in enumerate(events):
                px = inner_x + 40 + i * gap
                c.setFillColor(colors.white)
                c.setStrokeColor(accent if i % 2 == 0 else secondary)
                c.circle(px, yline, 16, stroke=1, fill=1)
                draw_icon(c, icon, px - 15, yline + 26, 30, accent if i % 2 == 0 else secondary)
                draw_centered(c, time, px - 44, yline - 38, 88, color=ink, size=10)
                draw_centered(c, title, px - 52, yline - 56, 104, color=muted, size=9, bold=False)
        elif kind == "setup":
            layers = [("Device", "Raspberry Pi", "pi"), ("Application", "FastAPI / APScheduler / SQLite", "cpu"), ("AI", "Ollama / rules / Isolation Forest", "brain"), ("Messaging", "Feishu webhook and callback", "message")]
            layer_h = (inner_h - 30) / 4
            for i, (title, note, icon) in enumerate(layers):
                ly = inner_y + inner_h - (i + 1) * layer_h - i * 10
                draw_panel(c, inner_x, ly, inner_w, layer_h, fill=colors.HexColor("#f8fbfd"), stroke=accent if i == 2 else line, radius=14)
                draw_icon(c, icon, inner_x + 18, ly + layer_h / 2 - 17, 34, accent if i == 2 else muted)
                draw_label(c, title, inner_x + 68, ly + layer_h / 2 + 6, color=ink, size=13)
                draw_label(c, note, inner_x + 68, ly + layer_h / 2 - 12, color=muted, size=9, bold=False)
        elif kind == "funnel":
            rows = [
                ("qwen3.5:2b", "too heavy"),
                ("qwen3.5:0.8b", "quantized but slow"),
                ("qwen2.5:0.5b", "fast but weak"),
                ("qwen3:1.7b + 0.6b", "hybrid final"),
            ]
            for i, (model, note) in enumerate(rows):
                rw = inner_w - i * 58
                rx = inner_x + i * 29
                ry = inner_y + inner_h - 70 - i * 68
                fill = colors.HexColor("#fff6e8") if i < 3 else colors.HexColor("#e9f6f1")
                stroke = secondary if i < 3 else accent
                draw_panel(c, rx, ry, rw, 50, fill=fill, stroke=stroke, radius=14)
                draw_label(c, model, rx + 18, ry + 29, color=ink, size=12)
                draw_label(c, note, rx + rw - 150, ry + 29, color=stroke, size=10)
        elif kind == "results":
            bars = [
                ("qwen2.5:0.5b", 14.3, "fast / weak", secondary),
                ("qwen3:1.7b", 55.6, "selected quality", accent),
                ("qwen3.5:0.8b", 74.8, "slow / empty", colors.HexColor("#b45f3c")),
            ]
            max_v = 80
            for i, (name, value, note, color) in enumerate(bars):
                by = inner_y + inner_h - 74 - i * 74
                draw_label(c, name, inner_x, by + 22, color=ink, size=11)
                c.setFillColor(colors.HexColor("#e8eef4"))
                c.roundRect(inner_x + 150, by + 15, inner_w - 250, 18, 9, stroke=0, fill=1)
                c.setFillColor(color)
                c.roundRect(inner_x + 150, by + 15, (inner_w - 250) * value / max_v, 18, 9, stroke=0, fill=1)
                draw_label(c, f"{value:.1f}s", inner_x + inner_w - 86, by + 20, color=color, size=11)
                draw_label(c, note, inner_x + 150, by - 2, color=muted, size=9, bold=False)
            draw_label(c, "2B candidate: rejected before final inference", inner_x, inner_y + 24, color=colors.HexColor("#b45f3c"), size=12)
        elif kind == "cold_start":
            steps = [("Load", "model into RAM", "db"), ("Generate", "Pi CPU speed", "cpu"), ("Think", "token budget", "brain"), ("Output", "visible summary", "doc")]
            step_w = (inner_w - 54) / 4
            for i, (title, note, icon) in enumerate(steps):
                sx = inner_x + i * (step_w + 18)
                icon_card(c, sx, inner_y + inner_h * 0.46, step_w, 92, icon, title, note, accent if i != 2 else secondary)
                if i < 3:
                    draw_arrow(c, sx + step_w + 3, inner_y + inner_h * 0.59, sx + step_w + 15, inner_y + inner_h * 0.59, muted)
            draw_panel(c, inner_x, inner_y + 28, inner_w, 64, fill=colors.HexColor("#fff7ed"), stroke=secondary, radius=14)
            draw_label(c, "Observed symptom", inner_x + 18, inner_y + 64, color=secondary, size=12)
            draw_label(c, "52-75 seconds, about 2 tokens/s, empty or length-limited visible output", inner_x + 18, inner_y + 42, color=ink, size=11)
        elif kind == "hybrid":
            cells = [("LLM", "language summaries", "brain"), ("Rules", "deterministic fallback", "check"), ("Isolation Forest", "device metrics", "cpu"), ("Scheduler", "local timing", "clock")]
            cell_w = (inner_w - 16) / 2
            cell_h = (inner_h - 16) / 2
            for i, (title, note, icon) in enumerate(cells):
                cx = inner_x + (i % 2) * (cell_w + 16)
                cy = inner_y + (1 - i // 2) * (cell_h + 16)
                icon_card(c, cx, cy, cell_w, cell_h, icon, title, note, accent if i in {0, 2} else secondary)
        elif kind == "privacy":
            steps = [("Feishu file", "message"), ("Temp file", "doc"), ("Local extract", "lock"), ("Local LLM", "brain"), ("Summary reply", "message")]
            gap = (inner_w - 64) / (len(steps) - 1)
            ymid = inner_y + inner_h * 0.58
            for i, (label, icon) in enumerate(steps):
                px = inner_x + 32 + i * gap
                draw_icon(c, icon, px - 20, ymid + 10, 40, accent if i != 4 else secondary)
                draw_centered(c, label, px - 48, ymid - 16, 96, color=ink, size=9)
                if i < len(steps) - 1:
                    draw_arrow(c, px + 26, ymid + 30, px + gap - 28, ymid + 30, muted)
            draw_panel(c, inner_x + inner_w * 0.18, inner_y + 26, inner_w * 0.64, 60, fill=colors.HexColor("#e9f6f1"), stroke=accent, radius=14)
            draw_label(c, "Privacy boundary", inner_x + inner_w * 0.18 + 18, inner_y + 62, color=accent, size=12)
            draw_label(c, "Raw document text stays on Raspberry Pi", inner_x + inner_w * 0.18 + 18, inner_y + 40, color=ink, size=11)
        elif kind == "tradeoff":
            p1 = (inner_x + inner_w * 0.50, inner_y + inner_h * 0.82)
            p2 = (inner_x + inner_w * 0.18, inner_y + inner_h * 0.20)
            p3 = (inner_x + inner_w * 0.82, inner_y + inner_h * 0.20)
            c.setStrokeColor(line)
            c.setLineWidth(2)
            c.line(*p1, *p2)
            c.line(*p2, *p3)
            c.line(*p3, *p1)
            draw_centered(c, "Quality", p1[0] - 45, p1[1] + 18, 90, color=accent, size=13)
            draw_centered(c, "Latency", p2[0] - 45, p2[1] - 25, 90, color=secondary, size=13)
            draw_centered(c, "Resources", p3[0] - 50, p3[1] - 25, 100, color=colors.HexColor("#b45f3c"), size=13)
            c.setFillColor(accent)
            c.circle(inner_x + inner_w * 0.56, inner_y + inner_h * 0.47, 10, stroke=0, fill=1)
            draw_label(c, "final route", inner_x + inner_w * 0.56 + 16, inner_y + inner_h * 0.47 - 4, color=ink, size=11)
        elif kind == "closing":
            draw_icon(c, "pi", inner_x + inner_w * 0.44, inner_y + inner_h * 0.50, 82, accent)
            draw_panel(c, inner_x + inner_w * 0.16, inner_y + inner_h * 0.18, inner_w * 0.68, 72, fill=colors.HexColor("#e9f6f1"), stroke=accent, radius=18)
            draw_centered(c, "Right local model for each edge job", inner_x + inner_w * 0.16, inner_y + inner_h * 0.18 + 42, inner_w * 0.68, color=ink, size=16)
            for i, label in enumerate(["Private", "Reliable", "Measured"]):
                draw_centered(c, label, inner_x + i * inner_w / 3, inner_y + inner_h - 40, inner_w / 3, color=accent if i != 1 else secondary, size=13)

    c = canvas.Canvas(str(pdf_path), pagesize=(width, height))
    c.setTitle("Edge Task Hub Presentation Slides")
    c.setAuthor("Edge Task Hub Team")
    for index, slide in enumerate(slides, 1):
        accent = palette[(index - 1) % len(palette)]
        c.setFillColor(bg)
        c.rect(0, 0, width, height, stroke=0, fill=1)
        c.setFillColor(accent)
        c.rect(0, height - 0.11 * inch, width, 0.11 * inch, stroke=0, fill=1)

        c.setFillColor(muted)
        c.setFont("Helvetica", 14)
        c.drawRightString(width - 0.56 * inch, height - 0.42 * inch, f"{index:02d}")
        c.setFillColor(accent)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin_x, height - top_margin, slide.get("kicker", "Edge AI").upper())

        y = height - top_margin - 0.42 * inch
        y = draw_wrapped(c, slide["title"], margin_x, y, "Helvetica-Bold", 31, 36, width - 2 * margin_x, text_color)
        y -= 0.04 * inch
        lead = slide.get("lead") or ""
        if lead:
            y = draw_wrapped(c, lead, margin_x, y, "Helvetica", 15.5, 21, width - 2 * margin_x, colors.HexColor("#31445d"))
            y -= 0.16 * inch

        if slide.get("table"):
            table_data = slide["table"]
            rows = [[paragraph(cell, 10.5, bold=True) for cell in table_data["headers"]]]
            rows.extend([[paragraph(cell, 10.2) for cell in row] for row in table_data["rows"]])
            table = Table(rows, colWidths=[2.55 * inch, 5.0 * inch, 4.25 * inch], repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef6")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c5ceda")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            table_width, table_height = table.wrapOn(c, width - 2 * margin_x, y)
            table.drawOn(c, margin_x, max(0.55 * inch, y - table_height))
        else:
            visual = slide.get("visual")
            visual_x = margin_x + 4.35 * inch
            visual_y = 0.58 * inch
            visual_w = width - visual_x - margin_x
            visual_h = max(3.9 * inch, y - visual_y - 0.05 * inch)
            if visual:
                draw_visual(c, visual, visual_x, visual_y, visual_w, visual_h, accent)
                text_w = visual_x - margin_x - 0.42 * inch
            else:
                text_w = width - 2 * margin_x
            card_y = y
            for item_index, item in enumerate(slide.get("bullets", [])[:5]):
                lines = wrap_text(item, "Helvetica", 11.2, text_w - 36)
                card_h = 32 + max(0, len(lines) - 1) * 12
                draw_panel(c, margin_x, card_y - card_h + 4, text_w, card_h, fill=colors.white, stroke=colors.HexColor("#d8e1ea"), radius=10)
                c.setFillColor(accent if item_index % 2 == 0 else secondary)
                c.circle(margin_x + 17, card_y - 12, 5, stroke=0, fill=1)
                c.setFillColor(text_color)
                c.setFont("Helvetica", 11.2)
                for line_index, text_line in enumerate(lines[:3]):
                    c.drawString(margin_x + 31, card_y - 16 - line_index * 12, text_line)
                card_y -= card_h + 8

        c.showPage()
    c.save()
    return pdf_path.exists() and pdf_path.stat().st_size > 1024


def slide_html(slides: list[dict[str, Any]], *, start_index: int = 1) -> str:
    pages = []
    for index, slide in enumerate(slides, start_index):
        bullets = "".join(f"<li>{escape_inline(item)}</li>" for item in slide.get("bullets", []))
        table_html = ""
        if slide.get("table"):
            table = slide["table"]
            table_html = html_table(table["headers"], table["rows"])
        kicker = f"<div class='kicker'>{escape_inline(slide.get('kicker', 'Edge AI'))}</div>"
        pages.append(
            "<section class='slide'>"
            f"<div class='slide-num'>{index:02d}</div>"
            f"{kicker}<h1>{escape_inline(slide['title'])}</h1>"
            f"<p class='lead'>{escape_inline(slide.get('lead', ''))}</p>"
            f"<ul>{bullets}</ul>{table_html}"
            "</section>"
        )
    css = """
    @page { size: 13.333in 7.5in; margin: 0; }
    body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: #172033; background: #f7f9fc; }
    .slide { position: relative; box-sizing: border-box; width: 13.333in; min-height: 7.5in; padding: 0.55in 0.72in; break-after: page; page-break-after: always; background: #f7f9fc; border-top: 0.11in solid #2f6f5e; }
    .slide:last-child { break-after: auto; page-break-after: auto; }
    .slide:nth-child(3n+2) { border-top-color: #315c9c; }
    .slide:nth-child(3n) { border-top-color: #b45f3c; }
    .slide-num { position: absolute; right: 0.55in; top: 0.34in; font-size: 14pt; color: #607086; }
    .kicker { font-size: 14pt; text-transform: uppercase; color: #2f6f5e; font-weight: 700; letter-spacing: 0.04em; margin-bottom: 0.14in; }
    h1 { font-size: 34pt; line-height: 1.05; margin: 0 0 0.18in; color: #152238; max-width: 10.8in; }
    .lead { font-size: 18pt; line-height: 1.28; color: #31445d; max-width: 11.2in; margin: 0 0 0.25in; }
    ul { margin: 0.08in 0 0; padding-left: 0.35in; max-width: 11.5in; }
    li { font-size: 18pt; line-height: 1.3; margin: 0.08in 0; }
    table { width: 100%; border-collapse: collapse; margin-top: 0.18in; font-size: 13pt; background: #ffffff; }
    th { background: #e8eef6; text-align: left; }
    th, td { border: 1px solid #c8d2df; padding: 0.08in; vertical-align: top; }
    code { font-family: Consolas, Menlo, monospace; background: #eef2f6; padding: 0 3px; }
    """
    return "<!doctype html><html><head><meta charset='utf-8'><title>Edge Task Hub Slides</title><style>" + css + "</style></head><body>" + "\n".join(pages) + "</body></html>"


def build_slides(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = evidence.get("tasks") or []
    daily = next((task for task in tasks if task.get("name") == "Daily Previous-Day News Summary"), {})
    return [
        {
            "title": "Edge Task Hub",
            "lead": "Resource-aware Edge AI automation on Raspberry Pi.",
            "bullets": ["Feishu is only the message channel.", "Raspberry Pi is the intelligence boundary.", "Local inference, scheduling, fallback, and monitoring happen on the edge device."],
            "visual": "hero",
        },
        {
            "title": "What We Must Prove",
            "lead": "This is an Edge AI course project, not a general chatbot project.",
            "bullets": ["Focus on setup, results, discussion, and analysis.", "Explain every result through edge constraints.", "Claim resource-aware local intelligence, not just LLM usage."],
            "visual": "proof",
        },
        {
            "title": "Why Edge AI?",
            "lead": "Cloud AI can ignore constraints that matter on a Raspberry Pi.",
            "bullets": ["Privacy: private document text should stay on the device.", "Memory and storage: model choice must fit real Pi limits.", "Latency policy: reminders must be punctual; summaries can wait.", "Reliability: the system still needs useful behavior when an LLM fails."],
            "visual": "constraints",
        },
        {
            "title": "System Architecture",
            "lead": "Feishu is the interface; the Raspberry Pi owns the local decision path.",
            "bullets": ["FastAPI exposes local APIs and Feishu callbacks.", "APScheduler controls reminder and summary timing.", "SQLite records tasks, runs, events, and metrics.", "Ollama and Isolation Forest provide local intelligence."],
            "visual": "architecture",
        },
        {
            "title": "User Workflows",
            "lead": "The project is a useful edge system, not only a model benchmark.",
            "bullets": [f"Daily previous-day news summary: {daily.get('cron_expr', '0 10 * * *')} local time.", "Built-in lunch and sleep reminders: 12:00 and 23:30.", "User-created reminders through Feishu text commands.", "Private document summaries from Feishu file events."],
            "visual": "workflows",
        },
        {
            "title": "Experimental Setup",
            "lead": "Experiments were run on the deployed Raspberry Pi, not only on a laptop.",
            "bullets": ["Runtime stack: FastAPI, APScheduler, SQLite, Ollama, and scikit-learn.", "LLM candidates: qwen3.5:2b, qwen3.5:0.8b, qwen2.5:0.5b, qwen3:1.7b, and qwen3:0.6b.", "Non-LLM intelligence: deterministic rules fallback and Isolation Forest."],
            "visual": "setup",
        },
        {
            "title": "Model Selection Journey",
            "lead": "Changing models was the experiment: each model tested a different edge constraint.",
            "bullets": ["2B candidate tested quality but failed deployability.", "0.8B quantized model tested memory reduction.", "0.5B model tested speed but lost quality.", "Final design routes by edge job."],
            "visual": "funnel",
        },
        {
            "title": "Model Results",
            "lead": "The final model choice balances quality, speed, memory, and deployability.",
            "bullets": ["qwen3:1.7b is selected for waitable summaries.", "qwen2.5:0.5b is fast but weaker.", "qwen3.5:0.8b is quantized but still slow.", "qwen3.5:2b is rejected before final inference."],
            "visual": "results",
        },
        {
            "title": "Why qwen3.5:0.8b Was Rejected",
            "lead": "Quantization helps model size, but it did not solve this edge workload.",
            "bullets": ["Recorded cold-start runs were about 52 to 75 seconds.", "Generation speed was about 2 tokens/s.", "Visible output was empty or length-limited.", "Likely causes: cold loading, Pi CPU speed, memory pressure, and thinking-token budget."],
            "visual": "cold_start",
        },
        {
            "title": "Why Non-LLM Models Matter",
            "lead": "Edge AI should use the smallest reliable intelligence for each local job.",
            "bullets": ["Rules fallback is deterministic when Ollama is unavailable.", "Isolation Forest is better than an LLM for CPU, memory, disk, temperature, and network metrics.", "APScheduler plus SQLite gives local timing control for reminders.", "This is hybrid Edge AI, not only LLM Edge AI."],
            "visual": "hybrid",
        },
        {
            "title": "Privacy and Automation Results",
            "lead": "Private processing stays local while Feishu only delivers commands and results.",
            "bullets": ["Feishu text can create scheduled reminders.", "Feishu files can trigger private document summaries.", "Document text is extracted and summarized locally.", "Verified checks cover Feishu parsing, slow-summary acceptance, document extraction, and English-only materials."],
            "visual": "privacy",
        },
        {
            "title": "Discussion and Analysis",
            "lead": "The strongest project argument is the edge tradeoff, not only the generated text.",
            "bullets": ["Daily summaries can wait for qwen3:1.7b quality.", "Reminders need local timing reliability.", "Private files need local processing.", "Device health needs lightweight local ML.", "One best model does not exist for all edge tasks."],
            "visual": "tradeoff",
        },
        {
            "title": "Limitations and Conclusion",
            "lead": "Edge Task Hub is a real Edge AI system with honest boundaries.",
            "bullets": ["Feishu public callback configuration is still required.", "Local LLM cold starts remain slow.", "Scanned PDFs need OCR in future work.", "Final claim: useful AI can run under edge constraints by choosing the right local model for each job."],
            "visual": "closing",
        },
    ]


def build_outline() -> str:
    return """# Presentation Outline

Target duration: 15 minutes plus 5 minutes for questions.

## 0:00-0:45 Slide 1: Title and claim

Say the project is a resource-aware Edge AI automation system on Raspberry Pi. Feishu is only the communication channel; local inference, scheduling, fallback, and monitoring are the edge contribution.

## 0:45-1:30 Slide 2: What we must prove

Say the course is not asking for a normal chatbot demo. The presentation must focus on experimental setup, results, discussion, and analysis, and every part must show Edge AI value.

## 1:30-2:40 Slide 3: Why Edge AI

Explain privacy, memory, storage, latency policy, and reliability. The key contrast is that cloud AI can ignore these constraints, while a Raspberry Pi cannot.

## 2:40-4:00 Slide 4: System architecture

Explain FastAPI, APScheduler, SQLite, Ollama, Feishu, and Isolation Forest. Emphasize that Feishu is only the interface and the Pi owns the local decision path.

## 4:00-5:10 Slide 5: User workflows

Cover daily news summary, built-in lunch and sleep reminders, user-created reminders, and private document summaries. This shows the system is useful beyond a benchmark.

## 5:10-6:30 Slide 6: Experimental setup

State that experiments were run on the deployed Raspberry Pi. Introduce the local LLM candidates and the non-LLM models.

## 6:30-8:20 Slide 7: Model selection journey

Explain why each model was tried: 2B for quality, 0.8B quantized for memory, 0.5B for speed, 1.7B for final quality, and 0.6B for short prompts.

## 8:20-9:50 Slide 8: Model results

Use the table to show the final decision. The main point is that the best model depends on the edge job, not only on size or speed.

## 9:50-10:50 Slide 9: Why qwen3.5:0.8b was rejected

Explain cold loading, Raspberry Pi CPU speed, memory pressure, and thinking-token budget. This is the clearest Edge AI model-selection lesson.

## 10:50-12:00 Slide 10: Why non-LLM models matter

Explain rules fallback, Isolation Forest, and APScheduler plus SQLite. Edge AI should use the smallest reliable intelligence for each local job.

## 12:00-13:10 Slide 11: Privacy and automation results

Show that Feishu only delivers commands and results. Private text is extracted and summarized locally on the Pi.

## 13:10-14:20 Slide 12: Discussion and analysis

Defend the tradeoff: summaries can wait for quality, reminders need timing reliability, private files need local processing, and device health needs lightweight ML.

## 14:20-15:00 Slide 13: Limitations and conclusion

Mention Feishu callback configuration, slow LLM cold starts, and future OCR for scanned PDFs. End with: useful AI can run under edge constraints by choosing the right local model for each job.
"""


def build_qa() -> str:
    return """# Q&A Preparation

## Why is this Edge AI rather than a normal web app?

The Raspberry Pi runs the intelligence locally: Ollama summaries, private document extraction, reminder scheduling, rules fallback, and Isolation Forest anomaly detection. Feishu is only the input and notification channel.

## Why did you try several models instead of choosing one directly?

Edge AI is constrained by memory, storage, cold start, latency, and privacy. The larger model direction tested quality but exposed deployability and storage limits. The quantized model direction reduced size but still had slow cold starts. The smallest model was fast but weaker. The final design chooses the model by edge job.

## Why was the earlier 2B-size model not used?

It was too heavy for a reliable Raspberry Pi deployment. The pull attempts were unstable and created storage pressure. For an edge device, a model that cannot be installed and operated reliably is not a valid final choice, even if its expected language quality is better.

## Why mention Ollama quantization?

Quantization is an Edge AI technique because it reduces model size and memory pressure. In this project, qwen3.5:0.8b showed that quantization helped fit the model better than a 2B candidate, but it did not fully solve cold-start latency or visible-output quality.

## Why did you select qwen3:1.7b if it is slower?

Daily news and private document summaries do not require strict live latency. Quality matters more, and the real qwen3:1.7b API run succeeded with fallback=false. Short prompts can still use qwen3:0.6b.

## Why did qwen3.5:0.8b time out or return empty output?

The recorded cold-start runs took about 52 to 75 seconds at about 2 tokens/s and produced empty or length-limited visible output. The likely causes are cold model loading, slow CPU generation, memory pressure, and Qwen-style thinking consuming output tokens before visible content. The runtime now sends think=false, but that model is still rejected for this project.

## What happens if Ollama is down?

The rules fallback still produces a deterministic local summary and records the attempted backend and failure reason. This keeps the edge workflow usable instead of silently failing.

## What protects private documents?

Files are downloaded to a temporary directory on the Raspberry Pi, text is extracted locally, the local model summarizes it, and the temporary file is removed. The document text is not sent to a cloud LLM.

## What model handles system health?

Isolation Forest handles system health. It is a better fit than an LLM for CPU, memory, disk, temperature, and network metrics because it is fast, local, and lightweight.

## Why call rules and Isolation Forest "models"?

They are program or classical ML models, not generative LLMs. Edge AI should use the smallest reliable intelligence for each local job. Rules are best for deterministic fallback, and Isolation Forest is best for numeric system metrics.

## What still needs work?

The Feishu app callback must be configured for public use, local LLM cold starts remain slow, scanned PDF OCR is not fully supported, and final names/student IDs must be added before submission.
"""


def write_supporting_docs(evidence: dict[str, Any]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "model-comparison.md").write_text(
        "# EdgeAI Model Comparison\n\n"
        f"Generated: {evidence['generated_at']}\n\n"
        "## Final Decision\n\n"
        "The selected news and private document summary model is `qwen3:1.7b`. "
        "`qwen3:0.6b` remains the fast local prompt candidate. "
        "`qwen3.5:2b`, `qwen3.5:0.8b`, and `qwen2.5:0.5b-instruct` are rejected for final summaries for different edge reasons: deployment stability, cold-start behavior, and quality loss.\n\n"
        "## Edge AI Lesson\n\n"
        "The model search was not random. Each candidate tested a different constraint: larger-model quality, quantized memory reduction, very-small-model speed, deterministic program reliability, and classical local anomaly detection.\n\n"
        + model_table()
        + "\n",
        encoding="utf-8",
    )
    (DOCS / "news-summary-evaluation.md").write_text(
        "# News Summary Evaluation\n\n"
        "The final news-summary policy is quality-first. The daily summary task can wait, so it uses `qwen3:1.7b` with a 300-second timeout. "
        "The verified API run completed in 55.624 seconds, used the Ollama backend, and did not fall back to rules. "
        "This is intentional: a daily previous-day summary should be useful, not only fast.\n\n"
        + md_table(
            ["Path", "Decision", "Edge reason"],
            [
                ["qwen3.5:2b", "Rejected", "Too heavy and unstable to install reliably on the Pi."],
                ["qwen3.5:0.8b", "Rejected", "Quantized but still slow on cold start and returned empty or length-limited output."],
                ["qwen2.5:0.5b-instruct", "Rejected for final summaries", "Fast, but weaker summary quality and semantic drift."],
                ["qwen3:1.7b", "Selected", "Best final quality among tested local candidates when waiting is acceptable."],
                ["qwen3:0.6b", "Kept", "Fast local prompt candidate for short interactions."],
                ["rules", "Kept", "Deterministic fallback for failures."],
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    (DOCS / "news-summary-demo.md").write_text(
        "# News Summary Demo\n\n"
        "- Task name: `EdgeAI News Summary Demo`\n"
        "- Main daily task: `Daily Previous-Day News Summary`\n"
        "- Daily schedule: `0 10 * * *`\n"
        "- Model: `qwen3:1.7b`\n"
        "- Notification channel: Feishu webhook\n"
        "- Edge AI point: the RSS summary is generated locally on the Raspberry Pi before notification.\n",
        encoding="utf-8",
    )
    (DOCS / "model-exploration-log.md").write_text(
        "# Model Exploration Log\n\n"
        "The project compared local model candidates on Raspberry Pi and changed the final policy after observing that news summaries do not need strict live latency. "
        "The exploration moved from larger-model quality, to quantized deployability, to tiny-model speed, and finally to a hybrid edge stack.\n\n"
        + model_table()
        + "\n",
        encoding="utf-8",
    )
    (DOCS / "final-report-notes.md").write_text(
        "# Final Report Notes\n\n"
        "Use `docs/final-report.pdf` as the report PDF and `docs/presentation-slides.pdf` as the presentation slide PDF. "
        "Names and student IDs still need to be added before final submission.\n\n"
        "Core defense sentence: Edge Task Hub keeps inference, private document processing, scheduling decisions, fallback logic, and device-health monitoring on the Raspberry Pi, while Feishu is only used for user interaction and notifications.\n",
        encoding="utf-8",
    )
    CHECKLIST_MD.write_text(
        "# Submission Checklist\n\n"
        "- Report PDF: `docs/final-report.pdf`\n"
        "- Presentation slides PDF: `docs/presentation-slides.pdf`\n"
        "- Source code: submit the GitHub link to Canvas, not the full project upload.\n"
        "- Add full names and student IDs before submission.\n"
        "- Keep all submitted material in English.\n"
        "- Emphasize Edge AI in setup, results, and discussion.\n",
        encoding="utf-8",
    )


def convert_html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    if shutil.which("soffice") is None:
        raise SystemExit("LibreOffice command not found: soffice. Install LibreOffice or run this script on the Raspberry Pi deployment.")
    if pdf_path.exists():
        pdf_path.unlink()
    profile = tempfile.mkdtemp(prefix="edge_task_hub_lo_")
    cmd = [
        "soffice",
        f"-env:UserInstallation=file://{profile}",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(html_path.parent),
        str(html_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
    if proc.returncode != 0:
        raise SystemExit((proc.stderr or proc.stdout or "LibreOffice PDF conversion failed").strip())
    if not pdf_path.exists() or pdf_path.stat().st_size < 1024:
        raise SystemExit(f"PDF conversion did not create a valid file: {pdf_path}")
    shutil.rmtree(profile, ignore_errors=True)


def convert_slides_to_pdf(slides: list[dict[str, Any]]) -> None:
    if shutil.which("soffice") is None:
        raise SystemExit("LibreOffice command not found: soffice. Install LibreOffice or run this script on the Raspberry Pi deployment.")
    if shutil.which("pdfunite") is None:
        raise SystemExit("pdfunite command not found. Install poppler-utils or run this script on the Raspberry Pi deployment.")
    if shutil.which("pdfseparate") is None:
        raise SystemExit("pdfseparate command not found. Install poppler-utils or run this script on the Raspberry Pi deployment.")
    if SLIDES_PDF.exists():
        SLIDES_PDF.unlink()

    tmpdir = Path(tempfile.mkdtemp(prefix="edge_task_hub_slides_"))
    profile = tempfile.mkdtemp(prefix="edge_task_hub_lo_")
    try:
        html_paths: list[Path] = []
        for index, slide in enumerate(slides, 1):
            path = tmpdir / f"slide-{index:02d}.html"
            path.write_text(slide_html([slide], start_index=index), encoding="utf-8")
            html_paths.append(path)

        cmd = [
            "soffice",
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmpdir),
            *[str(path) for path in html_paths],
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0:
            raise SystemExit((proc.stderr or proc.stdout or "LibreOffice slide PDF conversion failed").strip())

        pdf_paths = [tmpdir / f"slide-{index:02d}.pdf" for index in range(1, len(slides) + 1)]
        missing = [path.name for path in pdf_paths if not path.exists() or path.stat().st_size < 1024]
        if missing:
            raise SystemExit("Slide PDF conversion did not create valid files: " + ", ".join(missing))

        first_pages: list[Path] = []
        for index, pdf_path in enumerate(pdf_paths, 1):
            template = tmpdir / f"slide-{index:02d}-page-%d.pdf"
            separate = subprocess.run(
                ["pdfseparate", "-f", "1", "-l", "1", str(pdf_path), str(template)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if separate.returncode != 0:
                raise SystemExit((separate.stderr or separate.stdout or "pdfseparate failed").strip())
            first_page = tmpdir / f"slide-{index:02d}-page-1.pdf"
            if not first_page.exists() or first_page.stat().st_size < 1024:
                raise SystemExit(f"pdfseparate did not create the first page for {pdf_path.name}")
            first_pages.append(first_page)

        unite = subprocess.run(
            ["pdfunite", *[str(path) for path in first_pages], str(SLIDES_PDF)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if unite.returncode != 0:
            raise SystemExit((unite.stderr or unite.stdout or "pdfunite failed").strip())
        if not SLIDES_PDF.exists() or SLIDES_PDF.stat().st_size < 1024:
            raise SystemExit(f"Slide merge did not create a valid file: {SLIDES_PDF}")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    evidence = collect_evidence()
    EVIDENCE_JSON.write_text(json.dumps(evidence, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    report_md = build_report(evidence)
    REPORT_MD.write_text(report_md, encoding="utf-8")
    REPORT_HTML.write_text(markdown_to_html(report_md, title="Edge Task Hub Final Report"), encoding="utf-8")

    slides = build_slides(evidence)
    SLIDES_HTML.write_text(slide_html(slides), encoding="utf-8")
    OUTLINE_MD.write_text(build_outline(), encoding="utf-8")
    QA_MD.write_text(build_qa(), encoding="utf-8")
    write_supporting_docs(evidence)

    if reportlab_pdf(report_md, REPORT_PDF):
        print("wrote polished ReportLab report PDF")
    else:
        print("ReportLab not available; using LibreOffice report PDF conversion")
        convert_html_to_pdf(REPORT_HTML, REPORT_PDF)
    if slides_reportlab_pdf(slides, SLIDES_PDF):
        print("wrote polished ReportLab slides PDF")
    else:
        print("ReportLab not available; using LibreOffice slide PDF conversion")
        convert_slides_to_pdf(slides)

    LEGACY_REPORT_MD.write_text(report_md, encoding="utf-8")
    LEGACY_REPORT_HTML.write_text(REPORT_HTML.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copyfile(REPORT_PDF, LEGACY_REPORT_PDF)

    for path in [REPORT_MD, REPORT_PDF, SLIDES_HTML, SLIDES_PDF, OUTLINE_MD, QA_MD, CHECKLIST_MD, EVIDENCE_JSON]:
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
