# Q&A Preparation

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
