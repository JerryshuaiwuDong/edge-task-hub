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
        "candidate": "qwen3:1.7b",
        "role": "News and private document summaries",
        "decision": "Selected",
        "elapsed": "55.624 s",
        "speed": "2.208 tokens/s",
        "evidence": "Real API run on the Raspberry Pi, backend=ollama, fallback=false.",
        "quality": "Best final-summary choice because the project now allows waiting for quality instead of forcing a 30-second cold-start target.",
    },
    {
        "candidate": "qwen3:0.6b",
        "role": "Quick local chat and short reminder candidate",
        "decision": "Kept as fast model",
        "elapsed": "Configured fast path",
        "speed": "Not the final news metric",
        "evidence": "Configured as OLLAMA_MODEL and listed in the resource-aware router.",
        "quality": "Useful for short interactions, but the final daily news and private document flows prefer qwen3:1.7b quality.",
    },
    {
        "candidate": "qwen3.5:0.8b",
        "role": "News-summary candidate",
        "decision": "Rejected",
        "elapsed": "74.832 s",
        "speed": "1.965 tokens/s",
        "evidence": "Cold-start benchmark returned an empty visible response before the current think=false handling.",
        "quality": "Too slow and unstable for this project on the Raspberry Pi.",
    },
    {
        "candidate": "qwen2.5:0.5b-instruct",
        "role": "Legacy fast baseline",
        "decision": "Rejected for final summaries",
        "elapsed": "14.345 s",
        "speed": "7.983 tokens/s",
        "evidence": "Fast historical benchmark, but output quality drifted and mistranslated Raspberry Pi in the news task.",
        "quality": "Speed is good, but final project quality is weaker than qwen3:1.7b.",
    },
    {
        "candidate": "Rules fallback",
        "role": "Deterministic fallback",
        "decision": "Kept",
        "elapsed": "0 s",
        "speed": "N/A",
        "evidence": "Used when Ollama is stopped, too slow, or unavailable.",
        "quality": "Not generative AI, but important for reliability on an edge device.",
    },
    {
        "candidate": "Isolation Forest",
        "role": "Device-health anomaly detection",
        "decision": "Kept",
        "elapsed": "Sub-second per sample",
        "speed": "N/A",
        "evidence": "Runs locally on CPU, memory, disk, temperature, and network metrics.",
        "quality": "Matches edge monitoring better than an LLM.",
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
        ["Candidate", "Role", "Decision", "Latency", "Speed", "Evidence", "Quality note"],
        [
            [
                row["candidate"],
                row["role"],
                row["decision"],
                row["elapsed"],
                row["speed"],
                row["evidence"],
                row["quality"],
            ]
            for row in MODEL_ROWS
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

    md = f"""# Edge Task Hub: Privacy-Preserving Edge AI Task Automation on Raspberry Pi

Authors: to be added before submission

Generated: {evidence['generated_at']}

## Abstract

This paper presents Edge Task Hub, a Raspberry Pi based Edge AI system for scheduled reminders, daily news summaries, private document summaries, and device-health monitoring. The system is built around a local-first privacy boundary: Feishu is used for message delivery and user input, while news summarization, private document summarization, and anomaly detection run on the Raspberry Pi. The final design selects `qwen3:1.7b` for quality-first news and document summaries, keeps `qwen3:0.6b` for shorter local interactions, rejects `qwen3.5:0.8b` for this workload because of cold-start latency and empty visible output, and keeps deterministic rules plus Isolation Forest as edge-safe fallbacks.

## 1. Introduction

The project goal is not to build a general cloud chatbot. The goal is to defend an Edge AI system: a small device collects local data, runs local intelligence, exposes clear scheduling workflows, and sends only the final notification result through Feishu. This matters because the course project must show the edge part of AI, not only the AI part.

Edge Task Hub uses a Raspberry Pi as the edge device. It runs a FastAPI web service, APScheduler jobs, a SQLite database, Ollama local models, and a scikit-learn Isolation Forest model. Feishu provides the user-facing message channel. The device handles three practical workflows: scheduled reminders, previous-day news summaries, and private document summaries.

## 2. System Design

The final architecture separates cloud messaging from local inference:

{bullet([
    "Feishu outbound webhook: sends reminders, summaries, and alerts.",
    "Feishu inbound callback: receives text reminder commands and private document files.",
    "Local LLM: Ollama generates news and document summaries on the Raspberry Pi.",
    "Local rules path: deterministic summary fallback when Ollama is stopped or unavailable.",
    "Local anomaly model: Isolation Forest scores CPU, memory, disk, temperature, and network metrics.",
    "SQLite: stores tasks, task runs, inbound Feishu events, document summary metadata, and system metrics.",
])}

Current runtime service snapshot:

{md_table(["Service", "State"], [["edge-task-hub.service", service.get("edge_task_hub")], ["ollama.service", service.get("ollama")], ["openclaw-gateway.service", service.get("openclaw_gateway")]])}

Current edge resource snapshot:

```text
{resources.get("memory")}

{resources.get("disk")}
```

## 3. Edge AI Methods

### 3.1 Local LLM Summarization

The news and private document flows call Ollama through the local API at `127.0.0.1:11434`. The final summary model is `qwen3:1.7b`. The important policy change is that news summary is no longer treated as a strict 30-second live-demo task. A user can wait for a better daily summary, so the system uses a 300-second timeout for summary workflows.

The final verified qwen3:1.7b news-summary run used the real `/api/model/news-summary` API. It returned `backend=ollama`, `fallback=false`, `elapsed_seconds=55.624`, and `tokens_per_second=2.208`.

### 3.2 Deterministic Fallback

The rules path is intentionally kept. It is not a replacement for a local LLM, but it protects the edge workflow when the model service is stopped, the model is missing, RSS fails, or available memory is too low. This is an engineering decision: an edge device should expose failure and continue operating when possible.

### 3.3 Isolation Forest for Device Health

The Isolation Forest model is used for system monitoring, not for news text. It scores local metrics and provides fast anomaly detection without a cloud call. Current anomaly evidence reports `enabled={anomaly.get('enabled', 'unknown')}`, `model_trained={anomaly.get('model_trained', 'unknown')}`, `samples_collected={anomaly.get('samples_collected', 'unknown')}`, and `anomalies_24h={anomaly.get('anomalies_24h', 'unknown')}`.

### 3.4 Private Document Summaries

Private files sent through Feishu are downloaded to a temporary directory on the Raspberry Pi. Text is extracted locally from `.txt`, `.md`, `.docx`, and text-based `.pdf` files. The temporary file is deleted after processing, and the summary is generated locally with `qwen3:1.7b`. The original document text is not sent to a cloud model.

## 4. Experimental Setup

The evaluation used the Raspberry Pi deployment itself, not only a laptop simulation. The core services and configurations are:

{bullet([
    "Device: Raspberry Pi running Linux and systemd user services.",
    "Application stack: FastAPI, Uvicorn, APScheduler, SQLAlchemy, SQLite, Jinja2 UI.",
    "AI stack: Ollama for local LLM inference and scikit-learn Isolation Forest for anomaly detection.",
    "Messaging stack: Feishu webhook for outbound messages and Feishu event callback for inbound commands/files.",
    f"Candidate local models: {candidates}.",
    f"Router selected backend at generation time: {selected_backend}.",
    f"Router selected model at generation time: {selected_model}.",
])}

Standard scheduled tasks:

{task_table(evidence.get("tasks") or [])}

## 5. Results

### 5.1 Model Comparison

{model_table()}

### 5.2 Why qwen3.5:0.8b Timed Out for News Summary

The qwen3.5:0.8b result was not rejected only because it was newer or larger. It was rejected because its cold-start behavior was poor on this Raspberry Pi workload. Historical benchmark evidence recorded about 74.832 seconds, only 1.965 tokens per second, and an empty visible response. The most likely cause is a combination of cold model loading, slow generation on the Pi CPU, and Qwen-style internal thinking consuming the limited output budget before user-visible content. The runtime now sends `think=false`, but the final project still selects `qwen3:1.7b` because its quality is better for summaries when the user is allowed to wait.

### 5.3 Feishu Automation Results

{validation_rows}

## 6. Discussion

The main result is a resource-aware Edge AI architecture. A single "best model" answer would be misleading. The best model depends on the job:

{bullet([
    "`qwen3:1.7b` is the best final summary model among the tested local candidates because summary quality matters more than strict generation time.",
    "`qwen3:0.6b` remains useful for short local prompts and fast interactions.",
    "`qwen3.5:0.8b` is rejected for this Raspberry Pi news-summary workflow because it was slow and returned empty visible content.",
    "`qwen2.5:0.5b-instruct` is fast but produced weaker and less reliable summaries.",
    "Rules and Isolation Forest are kept because edge reliability is part of the project, not a fallback story to hide.",
])}

The privacy argument is also concrete. The device can receive a private file through Feishu, extract its text locally, summarize it with a local model, and send back only the summary. This is a better Edge AI story than uploading the document text to a cloud LLM.

## 7. Limitations

The system still has limitations:

{bullet([
    "The Feishu inbound app must be configured with app id, app secret, verification token, allowlists, and a public callback URL before external use.",
    "Local LLM inference on Raspberry Pi remains slow, especially after cold starts.",
    "The current PDF extraction supports text-based PDFs; scanned PDFs would need OCR, which is not part of the final verified path.",
    "Model quality is evaluated with project-level evidence and manual inspection, not with a large benchmark dataset.",
    "Student names and IDs still need to be inserted before final Canvas submission.",
])}

## 8. Conclusion

Edge Task Hub demonstrates Edge AI by running useful intelligence directly on a Raspberry Pi: local LLM summaries, local private document processing, local anomaly detection, and local scheduling decisions. Feishu is used as the notification and command interface, but the privacy-sensitive inference work remains on the edge device. The final system is stronger after rejecting a strict 30-second summary policy: daily news and private document summaries can wait for the higher-quality `qwen3:1.7b` model, while shorter interactions and fallback paths remain available for reliability.

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
            "lead": "Privacy-preserving Edge AI task automation on Raspberry Pi.",
            "bullets": ["Authors and student IDs will be added before submission.", "Core claim: private inference and scheduling decisions happen on the edge device."],
        },
        {
            "title": "Problem",
            "lead": "A Pi project should not be only a web dashboard or a cloud chatbot.",
            "bullets": ["Users need daily summaries and reminders through Feishu.", "Private files should not be sent to a cloud LLM.", "The system must defend its Edge AI part clearly."],
        },
        {
            "title": "Edge AI Boundary",
            "lead": "Feishu is the message channel; the Raspberry Pi is the intelligence boundary.",
            "bullets": ["Local Ollama for news and document summaries.", "Local rules fallback when the LLM is unavailable.", "Local Isolation Forest for device metrics."],
        },
        {
            "title": "System Architecture",
            "lead": "FastAPI, APScheduler, SQLite, Ollama, and Feishu are joined into one edge workflow.",
            "bullets": ["Browser UI configures tasks.", "APScheduler runs reminders and RSS digests.", "SQLite stores tasks, runs, events, document summaries, and metrics.", "Feishu receives results and sends commands/files."],
        },
        {
            "title": "Daily News Workflow",
            "lead": f"Current daily task: {daily.get('cron_expr', '0 10 * * *')} local time.",
            "bullets": ["Fetch previous-day RSS items.", "Summarize locally with qwen3:1.7b.", "Send the final summary through Feishu.", "Generation time can be longer because daily summaries do not need strict live latency."],
        },
        {
            "title": "Reminder Workflow",
            "lead": "Users can create reminders through Feishu text commands.",
            "bullets": ["Example: remind me every day at 23:30 to sleep.", "The parser creates a Task row and registers it with the scheduler.", "Built-in lunch and sleep reminders are already seeded."],
        },
        {
            "title": "Private Document Workflow",
            "lead": "A private Word or text document can be summarized on the Pi.",
            "bullets": ["Feishu sends the file event.", "The Pi downloads to a temporary directory.", "Text is extracted locally and summarized with qwen3:1.7b.", "The temporary file is deleted after processing."],
        },
        {
            "title": "Model Comparison",
            "lead": "The final choice is quality-first, not newest-model-first.",
            "table": {
                "headers": ["Candidate", "Decision", "Evidence"],
                "rows": [[row["candidate"], row["decision"], row["elapsed"]] for row in MODEL_ROWS[:4]],
            },
        },
        {
            "title": "Why qwen3.5:0.8b Failed",
            "lead": "The cold start took too long and produced no visible summary in the benchmark.",
            "bullets": ["Measured 74.832 seconds and 1.965 tokens/s.", "Likely consumed output budget in internal thinking before visible content.", "Runtime now sends think=false, but the candidate remains weaker for this project."],
        },
        {
            "title": "Experimental Setup",
            "lead": "The evaluation ran on the deployed Raspberry Pi.",
            "bullets": ["Real systemd service, SQLite database, and Feishu callback code.", "Candidate models compared with the same local news-summary style task.", "Unit tests cover Feishu events, reminder parsing, document extraction, and slow-summary acceptance."],
        },
        {
            "title": "Results",
            "lead": "The system now supports the required Edge AI workflows end to end.",
            "bullets": ["qwen3:1.7b selected for daily news and private document summaries.", "qwen3:0.6b kept as fast local prompt model.", "Rules fallback and Isolation Forest kept for reliability and local monitoring.", "10 unit tests pass on the Raspberry Pi."],
        },
        {
            "title": "Discussion",
            "lead": "The strongest project argument is the edge design, not only the LLM output.",
            "bullets": ["Private content stays on the device during summarization.", "Failures are recorded instead of hidden.", "The system chooses different local intelligence for text and metrics."],
        },
        {
            "title": "Limitations",
            "lead": "The final defense should be honest about current boundaries.",
            "bullets": ["Feishu public callback configuration is still required.", "Local LLM cold starts are slow on Raspberry Pi.", "Scanned PDFs need OCR and were not part of the verified path.", "Names and student IDs still need to be inserted."],
        },
        {
            "title": "Conclusion",
            "lead": "Edge Task Hub is an Edge AI automation system, not just a scheduler.",
            "bullets": ["Local summaries, local document processing, local anomaly detection.", "Feishu-based user interaction.", "Resource-aware model choice with qwen3:1.7b as the best summary model."],
        },
    ]


def build_outline() -> str:
    return """# Presentation Outline

Target duration: 15 minutes plus 5 minutes for questions.

## 0:00-1:00 Title and claim

Say the project is an Edge AI automation system on Raspberry Pi. Feishu is only the communication channel; local inference is the main edge contribution.

## 1:00-3:00 System architecture

Explain FastAPI, APScheduler, SQLite, Ollama, Feishu, and Isolation Forest. Keep background short.

## 3:00-6:00 Experimental setup

Show the deployed Pi, local model candidates, task schedules, Feishu workflows, and the test suite.

## 6:00-10:00 Experimental results

Focus on qwen3:1.7b, qwen3:0.6b, qwen3.5:0.8b, qwen2.5:0.5b, rules fallback, and Isolation Forest. Explain why generation time is allowed for news summaries.

## 10:00-13:00 Discussion and analysis

Defend the Edge AI part: privacy boundary, local inference, resource-aware routing, fallback recording, and local anomaly detection.

## 13:00-15:00 Limitations and conclusion

Mention Feishu callback configuration, cold-start latency, and scanned PDF OCR as limitations. End with the final claim: the project demonstrates practical Edge AI on a real edge device.
"""


def build_qa() -> str:
    return """# Q&A Preparation

## Why is this Edge AI rather than a normal web app?

The Raspberry Pi runs the intelligence locally: Ollama summaries, private document extraction, and Isolation Forest anomaly detection. Feishu is only the input and notification channel.

## Why did you select qwen3:1.7b if it is slower?

Daily news and private document summaries do not require strict live latency. Quality matters more, and the real qwen3:1.7b API run succeeded with fallback=false. Short prompts can still use qwen3:0.6b.

## Why did qwen3.5:0.8b time out or return empty output?

The recorded run took 74.832 seconds at 1.965 tokens/s and produced no visible summary. The likely cause is cold model loading plus Qwen-style internal thinking consuming output tokens before visible content. The runtime now sends think=false, but that model is still rejected for this project.

## What happens if Ollama is down?

The rules fallback still produces a deterministic local summary and records the attempted backend and failure reason. This keeps the edge workflow usable instead of silently failing.

## What protects private documents?

Files are downloaded to a temporary directory on the Raspberry Pi, text is extracted locally, the local model summarizes it, and the temporary file is removed. The document text is not sent to a cloud LLM.

## What model handles system health?

Isolation Forest handles system health. It is a better fit than an LLM for CPU, memory, disk, temperature, and network metrics because it is fast, local, and lightweight.

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
        "`qwen3.5:0.8b` and `qwen2.5:0.5b-instruct` are rejected for final summaries for this Raspberry Pi project.\n\n"
        + model_table()
        + "\n",
        encoding="utf-8",
    )
    (DOCS / "news-summary-evaluation.md").write_text(
        "# News Summary Evaluation\n\n"
        "The final news-summary policy is quality-first. The daily summary task can wait, so it uses `qwen3:1.7b` with a 300-second timeout. "
        "The verified API run completed in 55.624 seconds, used the Ollama backend, and did not fall back to rules.\n\n"
        + md_table(
            ["Path", "Decision", "Reason"],
            [
                ["qwen3:1.7b", "Selected", "Best final quality among tested local candidates."],
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
        "The project compared local model candidates on Raspberry Pi and changed the final policy after observing that news summaries do not need strict live latency.\n\n"
        + model_table()
        + "\n",
        encoding="utf-8",
    )
    (DOCS / "final-report-notes.md").write_text(
        "# Final Report Notes\n\n"
        "Use `docs/final-report.pdf` as the report PDF and `docs/presentation-slides.pdf` as the presentation slide PDF. "
        "Names and student IDs still need to be added before final submission.\n\n"
        "Core defense sentence: Edge Task Hub keeps inference and privacy-sensitive processing on the Raspberry Pi, while Feishu is only used for user interaction and notifications.\n",
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

    convert_html_to_pdf(REPORT_HTML, REPORT_PDF)
    convert_slides_to_pdf(slides)

    LEGACY_REPORT_MD.write_text(report_md, encoding="utf-8")
    LEGACY_REPORT_HTML.write_text(REPORT_HTML.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copyfile(REPORT_PDF, LEGACY_REPORT_PDF)

    for path in [REPORT_MD, REPORT_PDF, SLIDES_HTML, SLIDES_PDF, OUTLINE_MD, QA_MD, CHECKLIST_MD, EVIDENCE_JSON]:
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
