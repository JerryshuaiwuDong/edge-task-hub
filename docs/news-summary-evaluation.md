# News Summary Evaluation

The final news-summary policy is quality-first. The daily summary task can wait, so it uses `qwen3:1.7b` with a 300-second timeout. The verified API run completed in 55.624 seconds, used the Ollama backend, and did not fall back to rules. This is intentional: a daily previous-day summary should be useful, not only fast.

| Path | Decision | Edge reason |
| --- | --- | --- |
| qwen3.5:2b | Rejected | Too heavy and unstable to install reliably on the Pi. |
| qwen3.5:0.8b | Rejected | Quantized but still slow on cold start and returned empty or length-limited output. |
| qwen2.5:0.5b-instruct | Rejected for final summaries | Fast, but weaker summary quality and semantic drift. |
| qwen3:1.7b | Selected | Best final quality among tested local candidates when waiting is acceptable. |
| qwen3:0.6b | Kept | Fast local prompt candidate for short interactions. |
| rules | Kept | Deterministic fallback for failures. |
