# Q&A Preparation

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
