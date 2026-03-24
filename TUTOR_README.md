# 🎓 AI Conversational Tutor — Module README

A self-reprompting AI private tutor that lectures through a structured topic list, speaks via TTS, supports mid-lecture Q&A, and recursively summarizes its context to stay within token limits. The tutor automatically stops when all topics and subtopics are covered.

## Architecture

```
Frontend (React)                         Backend (FastAPI on :8001)
┌─────────────────────┐                  ┌────────────────────────────────┐
│   CompactTutor.tsx  │  POST /tutor/*   │  routers/tutor.py              │
│                     │ ◄──────────────► │    ↓                           │
│  • Start Session    │                  │  services/tutor_service.py     │
│  • Auto-continue    │                  │    ↓              ↓            │
│  • Ask Question     │                  │  Ollama Cloud    TTS Service   │
│  • Play TTS audio   │                  │  (LLM)           (Edge TTS)   │
└─────────────────────┘                  └────────────────────────────────┘
```

## How It Works

### 1. Session Start
The student provides a **list of topics** (each with subtopics). The backend creates an in-memory session that tracks:
- Current topic/subtopic index
- Running summary (recursively compressed)
- Transcript (sliding window of last 10 entries)
- Session status: `idle → lecturing → answering → finished`

### 2. Self-Reprompting Loop
The frontend calls `POST /tutor/continue` in a loop. Each call:
1. Builds a prompt from the **running summary** + **current subtopic** + **what's next**
2. Sends it to **Ollama Cloud** (LLM) to generate a 2–3 paragraph lecture chunk
3. **Compresses** the running summary by merging old summary + new content via a second LLM call
4. **Advances** the topic pointer to the next subtopic/topic
5. **Synthesizes speech** via Edge TTS and returns base64 audio
6. Returns `is_finished: true` when all topics are done

The frontend plays the audio, and when it ends, automatically calls `/continue` again — creating the self-reprompting behavior.

### 3. Mid-Lecture Q&A
When the student clicks **"Ask Question"**:
1. The auto-continue loop pauses
2. The question + running summary + current topic are sent to `POST /tutor/ask`
3. The LLM answers with full context awareness
4. The Q&A is folded into the running summary
5. The loop resumes from where it left off

### 4. Recursive Context Summarization
After every lecture chunk and every Q&A, the running summary is recompressed:
```
[Old Summary] + [New Content] → LLM → [Merged Compressed Summary]
```
This keeps the context window bounded regardless of session length.

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/tutor/start` | POST | Start a session with a topics list |
| `/tutor/continue` | POST | Generate next lecture chunk (call in a loop) |
| `/tutor/ask` | POST | Ask a question mid-lecture |
| `/tutor/status` | GET | Get current session state & progress |
| `/tutor/stop` | POST | End session early |
| `/tutor/health` | GET | Check Ollama Cloud connectivity |

### Start Session
```json
POST /tutor/start
{
  "topics": [
    {
      "name": "Python Variables",
      "subtopics": [
        "What is a variable",
        "Naming conventions",
        "Assigning values"
      ]
    },
    {
      "name": "Data Types",
      "subtopics": ["Integers and floats", "Strings", "Booleans"]
    }
  ],
  "voice": "en-US-JennyNeural"
}
```

### Continue (Self-Reprompt)
```json
POST /tutor/continue
{
  "session_id": "uuid-here",
  "include_audio": true
}

// Response:
{
  "text": "So let's talk about variables...",
  "audio_base64": "//uQxAAA...",
  "topic": "Python Variables",
  "subtopic": "What is a variable",
  "progress": 16.7,
  "is_finished": false
}
```

### Ask Question
```json
POST /tutor/ask
{
  "session_id": "uuid-here",
  "question": "Can a variable name start with a number?"
}
```

---

## Files

| File | Purpose |
|------|---------|
| `ai_service/services/tutor_service.py` | Core session engine — LLM calls, context summarization, topic tracking |
| `ai_service/routers/tutor.py` | FastAPI endpoints + TTS integration |
| `frontend/src/services/tutor.ts` | Axios API client for tutor endpoints |
| `frontend/src/components/CompactTutor.tsx` | React tutor panel UI with auto-continue loop |
| `frontend/src/pages/TestTutor.tsx` | Standalone test page (no auth required) |

---

## Configuration

Set these in `ai_service/services/.env`:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `https://ollama.com` | Ollama Cloud host |
| `OLLAMA_MODEL` | — | Cloud model name (e.g. `gpt-oss:20b`) |
| `OLLAMA_API_KEY` | — | API key from [ollama.com/settings/keys](https://ollama.com/settings/keys) |

Available cloud models: `gpt-oss:20b`, `gpt-oss:120b`, `deepseek-v3.1:671b`, `qwen3-coder:480b`

---

## Quick Start

```bash
# 1. Set your Ollama API key
echo "OLLAMA_API_KEY=your_key_here" > ai_service/services/.env
echo "OLLAMA_MODEL=gpt-oss:20b" >> ai_service/services/.env

# 2. Start the AI service
cd ai_service
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# 3. Start the frontend
cd frontend
npm run dev

# 4. Open the test page (no login required)
# → http://localhost:3000/test-tutor
```

---

## Future: Emotion Integration (Phase 4)

The platform already has FER (facial) and SER (speech) emotion recognition services. The next step is to:
1. Capture webcam frames → send to `/fer/predict-video`
2. Capture microphone audio → send to `/ser/predict-stream`
3. Feed detected emotions (e.g. `confused`, `frustrated`, `happy`) into the tutor's system prompt
4. The tutor adapts its tone, pace, and vocabulary based on the student's emotional state
