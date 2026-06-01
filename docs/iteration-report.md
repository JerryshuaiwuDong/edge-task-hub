# EdgeAI Iteration Report

Generated: 2026-05-25T12:56:34.830005+00:00

## Goal

Build a Raspberry Pi EdgeAI task assistant that collects local data, interacts with local models, and degrades gracefully when model or network paths fail.

## Iteration Timeline

- V0: Tried larger local LLM (`qwen2.5:1.5b`); it could run but timed out under the 30-second news-summary target.
- V1: Switched to `qwen2.5:0.5b-instruct`; short summaries can complete near the 30-second edge-device limit, so the demo uses a compact output budget.
- V2: Compared LLM and rules summaries; LLM is more flexible but quality is unstable, while rules are fast and reliable.
- V3: Added graceful degradation for Ollama stopped and RSS/network failure.
- V4: Added Isolation Forest anomaly detection and one-command final verification.
- V5: Replaced anomaly push alerts with a resource-aware maintenance center for project-only cleanup.

## Full Verification Matrix

| Scenario | Expected behavior | Observed result |
| --- | --- | --- |
| Ollama stopped | rules summary | backend=rules, fallback=true, duration=1214ms |
| Invalid RSS | local fallback news | feed_fallback=true, status=success, duration=228ms |
| Ollama running | local LLM summary | backend=ollama, model=qwen2.5:0.5b-instruct, elapsed=17.67s, tokens/s=7.811 |

## Verification Status

- Status: `PASS`
- Strict check: full verification fails if the Ollama-running path falls back to rules.

## Model Selection Comparison

- `qwen2.5:1.5b`: kept as the failed larger-model baseline because it exceeded the 30-second target.
- `qwen2.5:0.5b-instruct`: selected as the main local LLM path because it proves on-device model interaction and records model/elapsed/tokens/s.
- `rules`: selected as the required fallback because it is fast and deterministic when Ollama or RSS fails.
- `Isolation Forest`: selected for system-status analysis, not news summary, because it fits CPU/memory/disk/temperature/network anomaly detection.
- Maintenance center: selected as the resource-management iteration because edge devices need safe project-only cleanup instead of unsafe global memory tricks.
- Detailed comparison: `docs/model-comparison.md` and `data/model_comparison.jsonl`.

## Model Benchmark Snapshot

- Latest benchmark model: `qwen2.5:0.5b-instruct`
- Latest benchmark backend: `ollama`
- Latest benchmark wall seconds: `12.355`
- Latest benchmark tokens/s: `7.677`

## Edge Device Status

- CPU: `0.0%`
- Memory: `14.8%`
- Disk: `85.6%`
- Temperature: `58.9C`

## Service State

- Ollama: `stopped`
- OpenClaw: `stopped`
- pi-automation-scheduler: `inactive`

## Anomaly Detection

- Enabled: `True`
- Model trained: `True`
- Samples collected: `2806`
- 24h anomalies: `5`

## Resource-Aware Maintenance

- Mode: `conservative_auto_project_cleanup`
- Cleanup preview: `0.285` MB project cache
- Old metric rows: `0`
- Old task runs: `0`
- Recent maintenance logs: `2`

## Demo Entry Points

- News task: `http://127.0.0.1:8000/tasks/9`
- Model chat: `http://127.0.0.1:8000/model-chat`
- System status: `http://127.0.0.1:8000/system`
- Anomaly detection: `http://127.0.0.1:8000/anomaly`
- Maintenance center: `http://127.0.0.1:8000/maintenance`

## Conclusion

The final system demonstrates real edge-device/model interaction while preserving reliability through deterministic fallbacks. The local LLM is useful for short summaries, Isolation Forest explains resource anomalies, and the maintenance center turns those signals into safe project-only cleanup actions.

## Memory Snapshot

```text
               total        used        free      shared  buff/cache   available
Mem:           7.6Gi       1.1Gi       4.3Gi       128Mi       2.5Gi       6.5Gi
Swap:          2.0Gi        21Mi       2.0Gi
```
