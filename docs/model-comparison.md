# EdgeAI Model Comparison

Generated: 2026-05-29T09:50:15+00:00

## Final Decision

The selected news and private document summary model is `qwen3:1.7b`. `qwen3:0.6b` remains the fast local prompt candidate. `qwen3.5:0.8b` and `qwen2.5:0.5b-instruct` are rejected for final summaries for this Raspberry Pi project.

| Candidate | Role | Decision | Latency | Speed | Evidence | Quality note |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3:1.7b | News and private document summaries | Selected | 55.624 s | 2.208 tokens/s | Real API run on the Raspberry Pi, backend=ollama, fallback=false. | Best final-summary choice because the project now allows waiting for quality instead of forcing a 30-second cold-start target. |
| qwen3:0.6b | Quick local chat and short reminder candidate | Kept as fast model | Configured fast path | Not the final news metric | Configured as OLLAMA_MODEL and listed in the resource-aware router. | Useful for short interactions, but the final daily news and private document flows prefer qwen3:1.7b quality. |
| qwen3.5:0.8b | News-summary candidate | Rejected | 74.832 s | 1.965 tokens/s | Cold-start benchmark returned an empty visible response before the current think=false handling. | Too slow and unstable for this project on the Raspberry Pi. |
| qwen2.5:0.5b-instruct | Legacy fast baseline | Rejected for final summaries | 14.345 s | 7.983 tokens/s | Fast historical benchmark, but output quality drifted and mistranslated Raspberry Pi in the news task. | Speed is good, but final project quality is weaker than qwen3:1.7b. |
| Rules fallback | Deterministic fallback | Kept | 0 s | N/A | Used when Ollama is stopped, too slow, or unavailable. | Not generative AI, but important for reliability on an edge device. |
| Isolation Forest | Device-health anomaly detection | Kept | Sub-second per sample | N/A | Runs locally on CPU, memory, disk, temperature, and network metrics. | Matches edge monitoring better than an LLM. |
