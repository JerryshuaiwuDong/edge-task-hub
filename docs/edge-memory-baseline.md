# EdgeAI Memory Baseline

Date: 2026-05-22
Device: Raspberry Pi edge device

## Before Optimization

Observed while OpenClaw, Ollama, pi-automation-scheduler, Edge Task Hub, VS Code Server, and Chromium were running:

- Total memory: 7.6 GiB
- Used memory: about 2.9 GiB
- Available memory: about 4.8 GiB
- Swap: 2.0 GiB total, 0 used
- OpenClaw Gateway: about 379 MiB RSS
- Edge Task Hub: about 181 MiB RSS
- pi-automation-scheduler: about 143 MiB RSS including npm parent and node child
- Ollama service with no loaded model: about 34-98 MiB RSS
- VS Code Server and Chromium were the largest interactive-session memory consumers.

## Optimization Direction

- Keep Edge Task Hub as the main resident project.
- Run OpenClaw, Ollama, and the older Node scheduler only when needed for a demo or benchmark.
- Keep the anomaly model enabled, but sample every 300 seconds instead of every 60 seconds by default.
- Unload Ollama models immediately after API calls by using `keep_alive=0`.
- Cap numerical library thread pools in the Edge Task Hub systemd service with `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, and `MALLOC_ARENA_MAX=2`.

## After Optimization

Observed after disabling OpenClaw, Ollama, and pi-automation-scheduler, then restarting Edge Task Hub:

- Used memory: about 2.4 GiB
- Available memory: about 5.2 GiB
- Swap: 0 used
- Edge Task Hub: about 175 MiB RSS with anomaly detection enabled
- OpenClaw Gateway: inactive and disabled
- pi-automation-scheduler: inactive and disabled
- Ollama: inactive and disabled
- Only Edge Task Hub listens on port 8000; OpenClaw port 18789 and Ollama port 11434 are closed until started on demand.

This saves roughly 0.4-0.5 GiB of resident memory in the normal project mode while keeping the model benchmark path reproducible.

## On-Demand Model Commands

```bash
cd /home/pi3/edge-task-hub
scripts/edge_services.sh start ollama
scripts/edge_services.sh stop ollama
scripts/edge_services.sh start openclaw
scripts/edge_services.sh stop openclaw
```

The web page `/model-chat` reports whether Ollama or OpenClaw is running and shows these commands instead of starting services automatically.

## How To Reproduce

```bash
cd /home/pi3/edge-task-hub
scripts/memory_report.sh
```

For an optimized run, stop optional services first:

```bash
cd /home/pi3/edge-task-hub
scripts/edge_services.sh stop openclaw
scripts/edge_services.sh stop scheduler
scripts/edge_services.sh stop ollama
scripts/memory_report.sh
```
