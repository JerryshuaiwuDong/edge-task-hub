# Presentation Outline

Target duration: 15 minutes plus 5 minutes for questions.

## 0:00-0:45 Slide 1: Title and claim

Say the project is a resource-aware Edge AI automation system on Raspberry Pi. Feishu is only the communication channel; local inference, scheduling, fallback, and monitoring are the edge contribution.

## 0:45-1:30 Slide 2: What we must prove

Say the course is not asking for a normal chatbot demo. The presentation must focus on experimental setup, results, discussion, and analysis, and every part must show Edge AI value.

## 1:30-2:40 Slide 3: Why Edge AI

Explain privacy, memory, storage, latency policy, and reliability. The key contrast is that cloud AI can ignore these constraints, while a Raspberry Pi cannot.

## 2:40-4:00 Slide 4: System architecture

Explain FastAPI, APScheduler, SQLite, Ollama, Feishu, and Isolation Forest. Emphasize that Feishu is only the interface and the Pi owns the local decision path.

## 4:00-5:10 Slide 5: User workflows

Cover daily news summary, built-in lunch and sleep reminders, user-created reminders, and private document summaries. This shows the system is useful beyond a benchmark.

## 5:10-6:30 Slide 6: Experimental setup

State that experiments were run on the deployed Raspberry Pi. Introduce the local LLM candidates and the non-LLM models.

## 6:30-8:20 Slide 7: Model selection journey

Explain why each model was tried: 2B for quality, 0.8B quantized for memory, 0.5B for speed, 1.7B for final quality, and 0.6B for short prompts.

## 8:20-9:50 Slide 8: Model results

Use the table to show the final decision. The main point is that the best model depends on the edge job, not only on size or speed.

## 9:50-10:50 Slide 9: Why qwen3.5:0.8b was rejected

Explain cold loading, Raspberry Pi CPU speed, memory pressure, and thinking-token budget. This is the clearest Edge AI model-selection lesson.

## 10:50-12:00 Slide 10: Why non-LLM models matter

Explain rules fallback, Isolation Forest, and APScheduler plus SQLite. Edge AI should use the smallest reliable intelligence for each local job.

## 12:00-13:10 Slide 11: Privacy and automation results

Show that Feishu only delivers commands and results. Private text is extracted and summarized locally on the Pi.

## 13:10-14:20 Slide 12: Discussion and analysis

Defend the tradeoff: summaries can wait for quality, reminders need timing reliability, private files need local processing, and device health needs lightweight ML.

## 14:20-15:00 Slide 13: Limitations and conclusion

Mention Feishu callback configuration, slow LLM cold starts, and future OCR for scanned PDFs. End with: useful AI can run under edge constraints by choosing the right local model for each job.
