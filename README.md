# AI-Engagement-Agent-for-Discord

An AI-powered engagement bot for Discord that uses LLaMA 4 Scout (via Groq API) to enhance conversations by selectively responding and managing context for meaningful interactions.

---

## Features

- **Selective Engagement:** Responds only to direct questions, help requests, mentions, or unresolved messages after a delay  
- **Context Management:** Maintains conversation history (last 10 messages, 24 hours max) for coherent replies  
- **Message Analysis:** Detects questions, help requests, and mentions to decide when to engage  
- **Real-time Search:** Integrates DuckDuckGo for on-demand information retrieval  
- **Image Search:** Fetches images using Pexels API with `!image` command  
- **Analytics (WIP):** Tracks message stats, active users, and response patterns

---

## Tech Stack

- **Language Model:** meta-llama/llama-4-scout-17b-16e-instruct via Groq API  
- **APIs:** Discord API, DuckDuckGo, Pexels API  
- **Languages:** Python

---

## Usage

- Responds to `@bot` mentions, direct questions, and help requests  
- Use `!image <query>` to fetch relevant images  
- Maintains conversation flow with context-aware replies
- Image search integration  
- Member status tracking  
- Analytics dashboard in progress

---
