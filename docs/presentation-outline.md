# Presentation Outline

Target duration: 15 minutes plus 5 minutes for questions.

## 0:00-1:00 Title and claim

Say the project is an Edge AI automation system on Raspberry Pi. Feishu is only the communication channel; local inference is the main edge contribution.

## 1:00-3:00 System architecture

Explain FastAPI, APScheduler, SQLite, Ollama, Feishu, and Isolation Forest. Keep background short.

## 3:00-6:00 Experimental setup

Show the deployed Pi, local model candidates, task schedules, Feishu workflows, and the test suite.

## 6:00-10:00 Experimental results

Focus on qwen3:1.7b, qwen3:0.6b, qwen3.5:0.8b, qwen2.5:0.5b, rules fallback, and Isolation Forest. Explain why generation time is allowed for news summaries.

## 10:00-13:00 Discussion and analysis

Defend the Edge AI part: privacy boundary, local inference, resource-aware routing, fallback recording, and local anomaly detection.

## 13:00-15:00 Limitations and conclusion

Mention Feishu callback configuration, cold-start latency, and scanned PDF OCR as limitations. End with the final claim: the project demonstrates practical Edge AI on a real edge device.
