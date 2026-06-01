# Model Exploration Log

The project compared local model candidates on Raspberry Pi and changed the final policy after observing that news summaries do not need strict live latency. The exploration moved from larger-model quality, to quantized deployability, to tiny-model speed, and finally to a hybrid edge stack.

| Candidate | Role | Decision | Latency | Speed | Edge constraint | Quality note |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3.5:2b | Large local LLM baseline | Rejected before final inference | Pull stalled and regressed | N/A | Storage and deployment stability | A larger model may improve language quality, but it is not useful if the edge device cannot install and operate it reliably. |
| qwen3:1.7b | News and private document summaries | Selected | 55.624 s | 2.208 tokens/s | Quality-first local summarization | Best final-summary choice because daily news and private document summaries can wait for better local output. |
| qwen3:0.6b | Quick local chat and short reminder candidate | Kept as fast model | Configured fast path | Not the final news metric | Low-latency lightweight prompts | Useful for short interactions, but the final daily news and private document flows prefer qwen3:1.7b quality. |
| qwen3.5:0.8b | Quantized Ollama summary candidate | Rejected | 52-75 s | about 2 tokens/s | Memory pressure and cold-start latency | Quantization helped the model fit better than a 2B candidate, but cold-start latency and visible-output quality were still poor for this Pi workload. |
| qwen2.5:0.5b-instruct | Legacy fast baseline | Rejected for final summaries | 14.345 s | 7.983 tokens/s | Quality loss from very small LLM | Speed is good, but final project quality is weaker than qwen3:1.7b. |
| Rules fallback | Program model for deterministic fallback | Kept | 0 s | N/A | Reliability under failure | Not a generative LLM, but a local program model keeps the edge workflow reliable and explainable. |
| Isolation Forest | Classical ML model for device health | Kept | Sub-second per sample | N/A | Fast local metric scoring | A lightweight statistical model is a better fit than an LLM for edge resource monitoring. |
