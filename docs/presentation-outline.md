# Presentation Outline

Target duration: 15 minutes plus 5 minutes for questions.

## 0:00-1:00 Title and claim

Say the project is a resource-aware Edge AI automation system on Raspberry Pi. Feishu is only the communication channel; local inference, scheduling, fallback, and monitoring are the edge contribution.

## 1:00-3:00 Edge AI requirements

Explain the five constraints: privacy, memory, storage, latency policy, and reliability. Keep general background short.

## 3:00-5:00 System architecture

Explain FastAPI, APScheduler, SQLite, Ollama, Feishu, rules fallback, and Isolation Forest. Emphasize that the Pi is the intelligence boundary.

## 5:00-9:00 Experimental setup and model exploration

Show the model-selection chain: 2B-size model exposed storage and deployment limits, qwen3.5:0.8b exposed cold-start and memory pressure, qwen2.5:0.5b-instruct exposed quality loss, and qwen3:1.7b became the quality-first summary model.

## 9:00-12:00 Workflow results

Cover daily news at 10:00, user-created Feishu reminders, private document summaries, rules fallback, and local anomaly detection.

## 12:00-14:00 Discussion and analysis

Defend the Edge AI part: privacy boundary, resource-aware model choice, program models for reliability, and local metric monitoring.

## 14:00-15:00 Limitations and conclusion

Mention Feishu callback configuration, cold-start latency, and scanned PDF OCR as limitations. End with the final claim: the project demonstrates practical Edge AI on a real edge device.
