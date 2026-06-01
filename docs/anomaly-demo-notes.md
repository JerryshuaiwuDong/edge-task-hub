# Anomaly Detection Demo Notes

Generated: 2026-05-24T08:48:51.847611+00:00

## Goal

Show the non-LLM model path: Isolation Forest classifies Raspberry Pi system behavior using local metrics.

## Demo Run

- Stress seconds: `45`
- Worker processes: `1`
- Model trained before/after: `True` -> `True`
- Samples before/after: `2469` -> `2469`
- 24h anomalies before/after: `33` -> `33`

## System Snapshot

| Metric | Before | After |
| --- | ---: | ---: |
| CPU % | 2.4 | 0.0 |
| Memory % | 74.2 | 74.3 |
| Disk % | 88.9 | 88.9 |
| Temperature C | 58.4 | 63.8 |

## Recent Events

| Time | Score | CPU | Memory | Disk | Temp | Likely cause |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-05-24T08:42:38.218649Z | 0.10344771634670968 | 0.0 | 75.3 | 88.9 | 58.4 | High Network (31986.0 vs avg 29185.5) |
| 2026-05-24T08:37:38.220049Z | 0.07398294079704726 | 2.5 | 73.7 | 88.9 | 57.0 | High Network (14089.0 vs avg 29185.5) |
| 2026-05-24T08:32:38.217667Z | 0.12968384408874645 | 2.5 | 74.6 | 88.9 | 64.8 | High Network (64251.0 vs avg 29185.5) |
| 2026-05-24T08:27:38.218063Z | 0.1730721576824319 | 35.0 | 45.7 | 88.9 | 64.3 | High Network (255878.0 vs avg 29185.5) |
| 2026-05-24T08:22:38.221054Z | 0.0641568057480526 | 0.0 | 72.8 | 88.9 | 55.0 | High Network (8699.0 vs avg 29185.5) |

## Interpretation

This is the lightweight model path in the EdgeAI project. It does not need Ollama; it uses local system metrics and an Isolation Forest model to classify unusual device behavior.
