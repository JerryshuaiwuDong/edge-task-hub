# News Summary Evaluation

The final news-summary policy is quality-first. The daily summary task can wait, so it uses `qwen3:1.7b` with a 300-second timeout. The verified API run completed in 55.624 seconds, used the Ollama backend, and did not fall back to rules.

| Path | Decision | Reason |
| --- | --- | --- |
| qwen3:1.7b | Selected | Best final quality among tested local candidates. |
| qwen3:0.6b | Kept | Fast local prompt candidate for short interactions. |
| rules | Kept | Deterministic fallback for failures. |
