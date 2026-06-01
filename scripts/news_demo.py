#!/usr/bin/env python3
"""Create and run the EdgeAI RSS news-summary demo task."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
ITERATION_REPORT = ROOT / "docs" / "iteration-report.md"
TASK_NAME = "EdgeAI News Summary Demo"
FEED_URL = "https://www.raspberrypi.com/news/feed/"
DEMO_FALLBACK_ITEMS = [
    {
        "title": "Raspberry Pi collects RSS headlines and summarizes them locally",
        "link": "local://edge-rss-summary",
        "source": "Local EdgeAI demo",
    },
    {
        "title": "qwen3:1.7b produces higher-quality local summaries when the news task is allowed to wait",
        "link": "local://edge-llm-result",
        "source": "Local EdgeAI demo",
    },
    {
        "title": "The system records local model failures and uses a rules fallback when needed",
        "link": "local://edge-fallback",
        "source": "Local EdgeAI demo",
    },
]


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Edge Task Hub is not reachable at {BASE_URL}: {exc}") from exc
    return json.loads(raw) if raw else {}


def demo_body() -> dict[str, Any]:
    return {
        "name": TASK_NAME,
        "description": "End-to-end demo: RSS -> local model summary -> task record.",
        "task_type": "rss_digest",
        "schedule_kind": "recurring",
        "schedule_mode": "simple",
        "cron_expr": "0 8 * * *",
        "schedule_simple_json": {"pattern": "daily", "time": "08:00"},
        "timezone": "Asia/Shanghai",
        "payload_json": {
            "feed_url": FEED_URL,
            "limit": 3,
            "summary_mode": "auto",
            "notify": False,
            "fallback_items": DEMO_FALLBACK_ITEMS,
        },
        "use_ai": True,
        "enabled": True,
    }


def ensure_task() -> dict[str, Any]:
    existing = find_task()
    body = demo_body()
    if existing:
        task = api("PUT", f"/api/tasks/{existing['id']}", body)
        print(f"updated demo task #{task['id']}: {task['name']}")
        return task
    task = api("POST", "/api/tasks", body)
    print(f"created demo task #{task['id']}: {task['name']}")
    return task


def find_task() -> dict[str, Any] | None:
    tasks = api("GET", "/api/tasks")
    return next((task for task in tasks if task.get("name") == TASK_NAME), None)


def latest_run(task_id: int) -> dict[str, Any] | None:
    runs = api("GET", f"/api/tasks/{task_id}/runs?limit=1")
    return runs[0] if runs else None


def print_run(run: dict[str, Any] | None) -> None:
    if not run:
        print("no task run recorded yet")
        return
    print(f"run #{run['id']} status={run['status']} duration_ms={run.get('duration_ms')}")
    if run.get("error_text"):
        print(f"error={run['error_text']}")
    output = run.get("output_text") or ""
    preview = "\n".join(output.splitlines()[:14])
    print(preview)


def parse_meta(text: str | None) -> dict[str, str]:
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    meta: dict[str, str] = {}
    for part in first.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            meta[key.strip()] = value.strip()
    return meta


def run_service(action: str, target: str) -> None:
    subprocess.run([str(ROOT / "scripts" / "edge_services.sh"), action, target], check=True)


def wait_for_ollama(timeout: int = 30) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = api("GET", "/api/model/status")
        if status.get("ollama", {}).get("running"):
            return True
        time.sleep(1)
    return False


def free_memory() -> str:
    proc = subprocess.run(["free", "-h"], capture_output=True, text=True, check=False)
    return "\n".join(proc.stdout.splitlines()[:3])


def run_task() -> None:
    task = ensure_task()
    api("POST", f"/api/tasks/{task['id']}/run")
    print_run(latest_run(task["id"]))


def show_task() -> None:
    task = find_task()
    if not task:
        print("demo task does not exist yet; run scripts/news_demo.py ensure first")
        return
    print(f"task_url={BASE_URL}/tasks/{task['id']}")
    print(f"feed_url={task['payload_json'].get('feed_url')}")
    print(f"summary_mode={task['payload_json'].get('summary_mode')}")
    print(f"notify={task['payload_json'].get('notify')}")
    print_run(latest_run(task["id"]))


def verify(full: bool = False) -> None:
    task = ensure_task()
    model_status = api("GET", "/api/model/status")
    services = api("GET", "/api/system/services")
    anomaly = api("GET", "/api/anomaly/stats")
    maintenance = api("GET", "/api/maintenance/status")
    print(f"task_url={BASE_URL}/tasks/{task['id']}")
    print(f"ollama_running={model_status['ollama']['running']}")
    print(f"openclaw_running={model_status['openclaw']['running']}")
    print(f"anomaly_enabled={anomaly['enabled']} model_trained={anomaly['model_trained']} samples={anomaly['samples_collected']}")
    print(f"maintenance_mode={maintenance['policy']['mode']} cleanup_preview_mb={maintenance['preview']['estimated_mb']}")
    print("services=" + ", ".join(f"{svc['name']}:{svc['status']}" for svc in services["services"]))
    if model_status["ollama"]["running"]:
        print("fallback_check=skipped because Ollama is running; stop Ollama to verify rules fallback")
    else:
        api("POST", f"/api/tasks/{task['id']}/run")
        print_run(latest_run(task["id"]))
    print("llm_demo_commands:")
    print("  scripts/edge_services.sh start ollama")
    print("  scripts/news_demo.py run")
    print("  scripts/edge_services.sh stop ollama")
    if full:
        verify_full(task)


def verify_full(task: dict[str, Any]) -> None:
    print("\n== full verification ==")
    failures: list[str] = []
    rules_run: dict[str, Any] | None = None
    rss_run: dict[str, Any] | None = None
    llm_run: dict[str, Any] | None = None

    run_service("stop", "ollama")
    run_service("stop", "openclaw")
    run_service("stop", "scheduler")

    try:
        api("POST", f"/api/tasks/{task['id']}/run")
        rules_run = latest_run(task["id"])
        print("\n-- rules fallback --")
        print_run(rules_run)
        rules_meta = parse_meta((rules_run or {}).get("output_text"))
        if (rules_run or {}).get("status") != "success":
            failures.append("Ollama stopped check did not finish with status=success")
        if rules_meta.get("backend") != "rules":
            failures.append(f"Ollama stopped check expected backend=rules, got {rules_meta.get('backend')}")
        if rules_meta.get("fallback") != "true":
            failures.append("Ollama stopped check expected fallback=true")

        rss_run = run_invalid_rss_probe()
        print("\n-- invalid RSS fallback --")
        print_run(rss_run)
        rss_meta = parse_meta((rss_run or {}).get("output_text"))
        if (rss_run or {}).get("status") != "success":
            failures.append("Invalid RSS check did not finish with status=success")
        if rss_meta.get("feed_fallback") != "true":
            failures.append("Invalid RSS check expected feed_fallback=true")

        print("\n-- local LLM path --")
        run_service("start", "ollama")
        if not wait_for_ollama():
            failures.append("Ollama did not become reachable within 30 seconds")
        else:
            api("POST", f"/api/tasks/{task['id']}/run")
            llm_run = latest_run(task["id"])
            print_run(llm_run)
            llm_meta = parse_meta((llm_run or {}).get("output_text"))
            if (llm_run or {}).get("status") != "success":
                failures.append("Ollama running check did not finish with status=success")
            if llm_meta.get("backend") != "ollama":
                failures.append(f"Ollama running check expected backend=ollama, got {llm_meta.get('backend')}")
            if llm_meta.get("model") != "qwen2.5:0.5b-instruct":
                failures.append(f"Ollama running check expected model=qwen2.5:0.5b-instruct, got {llm_meta.get('model')}")
            if llm_meta.get("fallback") == "true":
                failures.append("Ollama running check unexpectedly used fallback=true")
            if not llm_meta.get("elapsed"):
                failures.append("Ollama running check did not record elapsed")
            if not llm_meta.get("tokens/s"):
                failures.append("Ollama running check did not record tokens/s")
    finally:
        run_service("stop", "ollama")
        run_service("stop", "openclaw")
        run_service("stop", "scheduler")

    system = api("GET", "/api/system/snapshot")
    services = api("GET", "/api/system/services")
    anomaly = api("GET", "/api/anomaly/stats")
    model = api("GET", "/api/model/status")
    maintenance = api("GET", "/api/maintenance/status")
    write_iteration_report(
        task=task,
        rules_run=rules_run,
        rss_run=rss_run,
        llm_run=llm_run,
        system=system,
        services=services,
        anomaly=anomaly,
        model=model,
        maintenance=maintenance,
        failures=failures,
    )
    print("\n-- final services --")
    print(", ".join(f"{svc['name']}:{svc['status']}" for svc in services["services"]))
    print(f"iteration_report={ITERATION_REPORT}")
    if failures:
        print("\n-- verification failures --")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

def run_invalid_rss_probe() -> dict[str, Any]:
    body = demo_body()
    body["name"] = "EdgeAI invalid RSS fallback probe"
    body["description"] = "Temporary full verification task for invalid RSS fallback."
    body["payload_json"] = dict(body["payload_json"])
    body["payload_json"]["feed_url"] = "https://invalid.invalid/edgeai-rss.xml"
    body["payload_json"]["summary_mode"] = "rules"
    body["use_ai"] = False
    task = api("POST", "/api/tasks", body)
    try:
        api("POST", f"/api/tasks/{task['id']}/run")
        run = latest_run(task["id"])
    finally:
        api("DELETE", f"/api/tasks/{task['id']}")
    return run or {}


def write_iteration_report(
    *,
    task: dict[str, Any],
    rules_run: dict[str, Any] | None,
    rss_run: dict[str, Any] | None,
    llm_run: dict[str, Any] | None,
    system: dict[str, Any],
    services: dict[str, Any],
    anomaly: dict[str, Any],
    model: dict[str, Any],
    maintenance: dict[str, Any],
    failures: list[str] | None = None,
) -> None:
    failures = failures or []
    rules_meta = parse_meta((rules_run or {}).get("output_text"))
    rss_meta = parse_meta((rss_run or {}).get("output_text"))
    llm_meta = parse_meta((llm_run or {}).get("output_text"))
    recent = model.get("recent_benchmark") or {}
    lines = [
        "# EdgeAI Iteration Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Goal",
        "",
        "Build a Raspberry Pi EdgeAI task assistant that collects local data, interacts with local models, and degrades gracefully when model or network paths fail.",
        "",
        "## Iteration Timeline",
        "",
        "- V0: Tried larger local LLM (`qwen2.5:1.5b`); it could run but timed out under the 30-second news-summary target.",
        "- V1: Switched to `qwen2.5:0.5b-instruct`; short summaries can complete near the 30-second edge-device limit, so the demo uses a compact output budget.",
        "- V2: Compared LLM and rules summaries; LLM is more flexible but quality is unstable, while rules are fast and reliable.",
        "- V3: Added graceful degradation for Ollama stopped and RSS/network failure.",
        "- V4: Added Isolation Forest anomaly detection and one-command final verification.",
        "- V5: Replaced anomaly push alerts with a resource-aware maintenance center for project-only cleanup.",
        "",
        "## Full Verification Matrix",
        "",
        "| Scenario | Expected behavior | Observed result |",
        "| --- | --- | --- |",
        f"| Ollama stopped | rules summary | backend={rules_meta.get('backend')}, fallback={rules_meta.get('fallback')}, duration={(rules_run or {}).get('duration_ms')}ms |",
        f"| Invalid RSS | local fallback news | feed_fallback={rss_meta.get('feed_fallback')}, status={(rss_run or {}).get('status')}, duration={(rss_run or {}).get('duration_ms')}ms |",
        f"| Ollama running | local LLM summary | backend={llm_meta.get('backend')}, model={llm_meta.get('model')}, elapsed={llm_meta.get('elapsed')}, tokens/s={llm_meta.get('tokens/s')} |",
        "",
        "## Verification Status",
        "",
        f"- Status: `{'PASS' if not failures else 'FAIL'}`",
        "- Strict check: full verification fails if the Ollama-running path falls back to rules.",
        *(f"- Failure: {failure}" for failure in failures),
        "",
        "## Model Selection Comparison",
        "",
        "- `qwen2.5:1.5b`: kept as the failed larger-model baseline because it exceeded the 30-second target.",
        "- `qwen2.5:0.5b-instruct`: selected as the main local LLM path because it proves on-device model interaction and records model/elapsed/tokens/s.",
        "- `rules`: selected as the required fallback because it is fast and deterministic when Ollama or RSS fails.",
        "- `Isolation Forest`: selected for system-status analysis, not news summary, because it fits CPU/memory/disk/temperature/network anomaly detection.",
        "- Maintenance center: selected as the resource-management iteration because edge devices need safe project-only cleanup instead of unsafe global memory tricks.",
        "- Detailed comparison: `docs/model-comparison.md` and `data/model_comparison.jsonl`.",
        "",
        "## Model Benchmark Snapshot",
        "",
        f"- Latest benchmark model: `{recent.get('model')}`",
        f"- Latest benchmark backend: `{recent.get('backend')}`",
        f"- Latest benchmark wall seconds: `{recent.get('wall_seconds')}`",
        f"- Latest benchmark tokens/s: `{recent.get('eval_tokens_per_second')}`",
        "",
        "## Edge Device Status",
        "",
        f"- CPU: `{system.get('cpu_percent')}%`",
        f"- Memory: `{system.get('memory_percent')}%`",
        f"- Disk: `{system.get('disk_percent')}%`",
        f"- Temperature: `{system.get('cpu_temp_c')}C`",
        "",
        "## Service State",
        "",
        *[f"- {svc['name']}: `{svc['status']}`" for svc in services.get("services", [])],
        "",
        "## Anomaly Detection",
        "",
        f"- Enabled: `{anomaly.get('enabled')}`",
        f"- Model trained: `{anomaly.get('model_trained')}`",
        f"- Samples collected: `{anomaly.get('samples_collected')}`",
        f"- 24h anomalies: `{anomaly.get('anomalies_24h')}`",
        "",
        "## Resource-Aware Maintenance",
        "",
        f"- Mode: `{maintenance.get('policy', {}).get('mode')}`",
        f"- Cleanup preview: `{maintenance.get('preview', {}).get('estimated_mb')}` MB project cache",
        f"- Old metric rows: `{maintenance.get('preview', {}).get('old_system_metrics')}`",
        f"- Old task runs: `{maintenance.get('preview', {}).get('old_task_runs')}`",
        f"- Recent maintenance logs: `{len(maintenance.get('recent_logs', []))}`",
        "",
        "## Demo Entry Points",
        "",
        f"- News task: `{BASE_URL}/tasks/{task['id']}`",
        f"- Model chat: `{BASE_URL}/model-chat`",
        f"- System status: `{BASE_URL}/system`",
        f"- Anomaly detection: `{BASE_URL}/anomaly`",
        f"- Maintenance center: `{BASE_URL}/maintenance`",
        "",
        "## Conclusion",
        "",
        "The final system demonstrates real edge-device/model interaction while preserving reliability through deterministic fallbacks. The local LLM is useful for short summaries, Isolation Forest explains resource anomalies, and the maintenance center turns those signals into safe project-only cleanup actions.",
        "",
        "## Memory Snapshot",
        "",
        "```text",
        free_memory(),
        "```",
    ]
    ITERATION_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ensure", "run", "show", "verify"], nargs="?", default="ensure")
    parser.add_argument("--full", action="store_true", help="Run full final verification and write iteration report.")
    args = parser.parse_args()
    if args.command == "ensure":
        task = ensure_task()
        print(f"task_url={BASE_URL}/tasks/{task['id']}")
    elif args.command == "run":
        run_task()
    elif args.command == "verify":
        verify(full=args.full)
    else:
        show_task()
    return 0


if __name__ == "__main__":
    sys.exit(main())
