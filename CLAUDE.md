# AI-Powered Personalized Learning Platform — CLAUDE.md

This file is the authoritative reference for Claude Code when working on this project.
It covers architecture, all services, data models, API contracts, frontend structure, and current implementation status.

---

## Project Overview

An AI-driven e-learning platform that delivers personalized learning pathways.
Students take a **placement assessment** before starting a course, and the system adapts content difficulty and progression based on their performance.
The platform includes interactive slide-based lessons, an AI tutor (Dr. Nova) with a 3D avatar, a coding practice arena with graded evaluation, and a gamification layer.

---

## Architecture

```
React Frontend (port 3000)
        │
        │ REST/JSON (axios, Token auth)
        ▼
Django REST API (port 8000)
        │                    │
        │ DB (ORM)            │ HTTP proxy
        ▼                    ▼
Supabase PostgreSQL    FastAPI AI Service (port 8001)
                             │
          ┌──────────────────┼──────────────────────────────┐
          ▼          ▼       ▼        ▼       ▼      ▼      ▼
       Whisper   Groq API  T5 model  Ollama  edge-tts ChromaDB  A2F NIM
       (ASR)   (Qwen/llama)(LeetCode)(Dr.Nova)(TTS)  (RAG)  (gRPC:52000)
```

**Supporting infra (docker-compose.yml):** PostgreSQL 15 (port 5432), MongoDB 6 (port 27017), Redis 7 (port 6379).

---

## How to Start Servers

```bash
# Frontend
cd frontend && npm run dev          # http://localhost:3000

# Backend
cd backend
source venv/Scripts/activate        # Windows
python manage.py runserver          # http://localhost:8000

# AI Service
cd ai_service
source venv/Scripts/activate
uvicorn main:app --port 8001 --reload   # http://localhost:8001

# RAG Indexer (run once to populate ChromaDB before starting AI service)
cd rag_pipeline
source venv/Scripts/activate
python scripts/run_indexer.py
```

---

## Environment Variables

### Backend (`backend/.env`)
```
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=postgres
DB_USER=postgres.<SUPABASE_PROJECT_REF>
DB_PASSWORD=...
DB_HOST=aws-0-<region>.pooler.supabase.com
DB_PORT=6543
CORS_ALLOWED_ORIGINS=http://localhost:3000
AI_SERVICE_URL=http://localhost:8001
```

### AI Service (`ai_service/.env`)
```
CORS_ORIGINS=http://localhost:8000
GROQ_API_KEY=...
OLLAMA_BASE_URL=https://...          # Ollama Cloud endpoint for Dr. Nova
OLLAMA_MODEL=llama3.2
OLLAMA_API_KEY=...
GROQ_MODEL_CODING=qwen/qwen3-32b    # LLM for coding question gen, rubric, evaluation, hints
CODING_USE_T5=false                 # Set to "true" to fall back to T5 for question generation only
A2F_GRPC_HOST=localhost             # Audio2Face NIM gRPC host (optional)
A2F_GRPC_PORT=52000                 # Audio2Face NIM gRPC port (optional)
```

### Frontend (`frontend/.env`)
```
VITE_API_URL=http://localhost:8000/api
VITE_AI_URL=http://127.0.0.1:8001
VITE_AI_SERVICE_URL=http://localhost:8001
```

### RAG Pipeline (`rag_pipeline/.env`)
```
OLLAMA_HOST=https://...
OLLAMA_MODEL=gpt-oss:20b
OLLAMA_API_KEY=...
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
CHROMA_DB_PATH=./data/chroma
CHROMA_COLLECTION_NAME=course_chunks
CHUNK_SIZE_MIN=300
CHUNK_SIZE_MAX=400
CHUNK_OVERLAP=50
```

---

## Backend (Django REST Framework)

### Project Layout
```
backend/
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py / wsgi.py
└── apps/
    ├── core/             ← Health check
    ├── users/            ← Auth, profiles, preferences
    ├── courses/          ← Courses, modules, lessons, enrollments, coding proxies
    ├── progress/         ← Lesson completions, activity logs, AI chat logs, practice XP
    └── gamification/     ← Achievements, daily study stats
```

### App: `users`

#### Models
| Model | Key Fields |
|-------|-----------|
| `User` | `username`, `email`, `role` (student/admin/instructor), `bio`, `profile_picture` |
| `StudentProfile` | `user` (1-1), `level`, `current_xp`, `current_streak`, `longest_streak`, `total_minutes_learned`, `daily_goal_minutes`, `days_active`, `messages_count` |
| `UserPreferences` | `user` (1-1), `email_notifications`, `ai_tutor_voice_enabled`, `study_reminders` |
| `ActiveSession` | `user`, `device_info`, `ip_address` |

#### Endpoints (`/api/users/`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/login/` | Login, returns token |
| POST | `/signup/` | Register new user |
| GET/PATCH | `/me/` | Current user profile |
| GET/PATCH | `/student-profile/` | Student gamification profile |
| GET/PATCH | `/preferences/` | Feature toggle preferences |
| POST | `/logout/` | Delete auth token |
| GET | `/admin-students/` | List all students with gamification stats (admin only) |
| GET | `/leaderboard/` | Top 20 students by XP + current user's rank |

---

### App: `courses`

#### Models
| Model | Key Fields |
|-------|-----------|
| `Course` | `title`, `description`, `instructor` (FK→User), `syllabus` (JSON), `difficulty`, `status`, `price`, `tags`, `total_lessons_count`, `avg_rating` |
| `Module` | `course` (FK), `title`, `module_order` |
| `Lesson` | `module` (FK), `title`, `lesson_order` |
| `Slide` | `lesson` (FK), `content_json`, `slide_order` |
| `CodeChallenge` | `lesson` (FK), `problem_text`, `starter_code`, `solution_code`, `test_cases_json`, `hint_text` |
| `Enrollment` | `student` (FK→User), `course` (FK), `placement_score`, `current_lesson` (FK→Lesson), `current_pathway` (JSON), `progress_percentage`, `current_score`, `is_paid`, `is_pathway_ready` (bool), `is_assessment_started` (bool), `last_accessed` |

**`is_pathway_ready`** — set to `True` after placement assessment completes and the personalized pathway has been generated. `RequirePathway` guard on `LiveSession` redirects to assessment if `False`.

#### Endpoints (`/api/courses/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/courses/` | List courses (search, filter, ordering) — cached 15 min |
| GET | `/courses/:id/` | Course detail — cached 15 min |
| POST | `/courses/:id/rate/` | Submit star rating |
| GET/POST | `/modules/?course_id=X` | Modules for a course |
| GET/POST | `/lessons/?module_id=X` | Lessons for a module |
| GET | `/lessons/:id/` | Lesson detail with nested slides + code_challenges |
| GET | `/slides/?lesson_id=X` | Slides for a lesson |
| GET | `/code-challenges/?lesson_id=X` | Code challenges (no solution_code) |
| GET/POST | `/enrollments/` | List / create enrollments |
| PATCH | `/enrollments/:id/` | Update enrollment |
| POST | `/coding/evaluate/` | Proxy → AI service (legacy Pass/Fail) |
| POST | `/coding/evaluate-graded/` | Proxy → AI service (0–100 score + breakdown) |
| POST | `/coding/rubric/` | Proxy → AI service (generate rubric for a question) |
| POST | `/coding/hint/` | Proxy → AI service (progressive hints) |
| GET | `/admin/stats/` | Admin summary stats |
| GET | `/my-courses/` | Courses taught by requesting instructor |
| GET | `/my-courses/:id/students/` | Enrollments for an instructor's course |

---

### App: `progress`

#### Models
| Model | Key Fields |
|-------|-----------|
| `LessonCompletion` | `enrollment` (FK), `lesson` (FK), `status`, `score`, `completed_at`, `time_spent_minutes` |
| `SystemActivityLog` | `user` (FK), `action_type`, `description`, `metadata` (JSON) |
| `AIChatLog` | `user` (FK), `lesson` (FK), `user_audio_url`, `transcript_text`, `ai_response_text` |

#### Endpoints (`/api/progress/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/lesson-completions/?enrollment_id=X` | List completions |
| POST | `/lesson-completions/` | Create completion record |
| POST | `/lesson-completions/:id/complete/` | Mark lesson completed |
| PATCH | `/lesson-completions/:id/` | Update completion |
| GET | `/activity-logs/` | User activity history |
| GET | `/ai-chat-logs/?lesson_id=X` | AI chat history |
| POST | `/practice-completion/` | Award XP for coding practice (score ≥ 60 → +25 XP, score ≥ 90 → +50 XP) |

---

### App: `gamification`

#### Models
| Model | Key Fields |
|-------|-----------|
| `Achievement` | `name`, `description`, `xp_reward`, `icon_url` |
| `UserAchievement` | `user` (FK), `achievement` (FK), `earned_at` |
| `DailyStudyStats` | `user` (FK), `study_date`, `hours_spent` |

#### Endpoints (`/api/gamification/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/achievements/` | All available achievements |
| GET | `/achievements/mine/` | Current user's earned achievements |
| GET/POST | `/daily-stats/` | Study time log |

#### Gamification Signals
Fires on every `LessonCompletion` save where `status = "Completed"`:
- Awards **+50 XP** per lesson (+100 bonus for the very first lesson)
- Recalculates **level** (`XP ÷ 200 + 1`, capped at 10)
- Auto-logs **0.5 hours** to `DailyStudyStats`
- Updates **streak**, **longest_streak**, **days_active**
- Checks and awards achievements at defined thresholds

---

## AI Service (FastAPI)

### Layout
```
ai_service/
├── main.py               ← FastAPI app, CORS, all router inclusions
├── routers/
│   ├── health.py         ← GET /health
│   ├── asr.py            ← POST /asr/transcribe
│   ├── coding.py         ← POST /api/coding/generate, /evaluate, /evaluate-graded, /rubric, /hint
│   ├── tutor.py          ← POST /tutor/start|continue|ask|stop|relevance; GET /tutor/status|health
│   ├── tts.py            ← POST /tts/synthesize; GET /tts/voices, /tts/health
│   ├── fer.py            ← POST /fer/analyze, /fer/predict, /fer/predict-video
│   ├── ser.py            ← POST /ser/analyze, /ser/predict, /ser/predict-stream
│   ├── intent.py         ← POST /intent/classify; GET /intent/health
│   ├── rag.py            ← POST /rag/ask; GET /rag/health
│   ├── slides.py         ← POST /slides/generate; GET /slides/health
│   ├── assessments.py    ← POST /assessments/generate, /assessments/submit-placement; GET /assessments/health
│   ├── profiler.py       ← POST /profiler/update, /profiler/fuse-emotions
│   ├── session.py        ← GET/PATCH/DELETE /session/{session_id}
│   ├── student_context.py← GET /student-context/{student_id}/{course_id}
│   └── a2f_health.py     ← GET /a2f/health (Audio2Face NIM gRPC connectivity check)
├── services/
│   ├── asr_service.py
│   ├── coding_service.py ← Qwen/qwen3-32b (primary) + T5 fallback; question history dedup
│   ├── evaluator.py      ← Graded evaluation: 0–100 score, letter grade, per-criterion breakdown
│   ├── rubric_service.py ← Generates 4–5 weighted criteria (sum=100); LRU cache by question hash
│   ├── hint_service.py   ← 3-level progressive hints (conceptual → approach → pseudocode)
│   ├── tutor_service.py  ← Ollama Cloud (Dr. Nova), in-memory sessions
│   ├── tts_service.py    ← edge-tts; default voice: en-US-AndrewMultilingualNeural
│   ├── intent_service.py ← TinyBERT intent classifier
│   ├── assessment_service.py ← AI assessment generation with semantic dedup
│   ├── category_service.py   ← Topic category classification for assessments
│   ├── profiler_service.py   ← Student profile update + emotion fusion (Groq LLM arbitration)
│   ├── session_store.py      ← SharedSessionStore singleton (in-memory; Redis-ready)
│   ├── student_context_store.py ← Persists UnifiedStudentContext to JSON files
│   └── a2f_client.py         ← Audio2Face NIM gRPC client for 3D avatar blendshape data
├── schemas/
│   ├── coding.py         ← TopicRequest, SubmitRequest, RubricRequest, EvaluateGradedRequest,
│   │                        GradedResultResponse, HintRequest, HintResponse, BreakdownItem
│   ├── student_context.py← UnifiedStudentContext, StudentProfileState, LiveSessionState
│   └── intent.py         ← IntentRequest, IntentResponse
├── static/
│   └── metaHumanHead_52shapekeys_01.gltf  ← 3D avatar mesh (served at /static/)
├── tests/
│   ├── test_conversational_agent.py
│   ├── test_profiler_service.py
│   └── test_session_store.py
├── intent_model/         ← TinyBERT intent classifier weights + architecture
└── models/
    └── clean_question_model/  ← Custom fine-tuned T5 (LeetCode problems, legacy)
```

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/asr/transcribe` | Audio → text (Whisper) |
| GET | `/asr/health` | Whisper model status |
| POST | `/api/coding/generate` | Generate coding problem from topic |
| POST | `/api/coding/evaluate` | Evaluate code (legacy Pass/Fail) |
| POST | `/api/coding/evaluate-graded` | Graded evaluation: 0–100 + letter grade + breakdown |
| POST | `/api/coding/rubric` | Generate weighted rubric for a question |
| POST | `/api/coding/hint` | Progressive hint (level 1–3) |
| POST | `/tutor/start` | Start tutor session → `{ session_id }` |
| POST | `/tutor/continue` | Get next lecture chunk → `{ text, audio_base64, progress, is_finished, subtopic }` |
| POST | `/tutor/ask` | Ask Dr. Nova a question |
| POST | `/tutor/stop` | End tutor session |
| GET | `/tutor/status/{session_id}` | Session status |
| POST | `/tutor/relevance` | LLM relevance check |
| GET | `/tutor/health` | Tutor service health |
| POST | `/tts/synthesize` | Text → MP3 audio |
| GET | `/tts/voices` | List available voices |
| GET | `/tts/health` | TTS health |
| POST | `/fer/analyze` | Image → facial emotion |
| POST | `/fer/predict` | Image → facial emotion (alias) |
| POST | `/fer/predict-video` | Video → facial emotion per frame |
| POST | `/ser/analyze` | Audio → speech emotion |
| POST | `/ser/predict` | Audio → speech emotion (alias) |
| POST | `/ser/predict-stream` | Streaming speech emotion |
| POST | `/intent/classify` | Text → intent classification (TinyBERT, 5 classes) |
| GET | `/intent/health` | Intent model status |
| POST | `/rag/ask` | RAG-grounded answer from textbooks |
| GET | `/rag/health` | ChromaDB status |
| POST | `/slides/generate` | Generate structured slides from lesson content |
| GET | `/slides/health` | Slides service health |
| POST | `/assessments/generate` | AI-generated placement assessment questions |
| POST | `/assessments/submit-placement` | Submit placement score → updates student context |
| GET | `/assessments/health` | Assessment service health |
| POST | `/profiler/update` | Rewrite student profile from session emotion log |
| POST | `/profiler/fuse-emotions` | Fuse FER + SER → single emotion (LLM arbitration on conflict) |
| GET | `/session/{session_id}` | Get shared session state |
| PATCH | `/session/{session_id}` | Update shared session state (slide index, tutor events, etc.) |
| DELETE | `/session/{session_id}` | Clean up session from SharedSessionStore |
| GET | `/student-context/{student_id}/{course_id}` | Get persisted student context |
| GET | `/a2f/health` | Audio2Face NIM gRPC connectivity check |
| GET/POST | `/pathway/...` | Personalized pathway generation (course_pathway module) |

### Code Generation & Evaluation Flow (updated)
1. `POST /api/coding/generate` — Qwen/qwen3-32b generates question + starter code. Tracks history per topic (max 10) to prevent repeats. T5 fallback via `CODING_USE_T5=true`.
2. `POST /api/coding/rubric` — Qwen generates 4–5 weighted criteria summing to 100. Cached by question hash (LRU, max 200).
3. Student writes code in Monaco editor.
4. `POST /api/coding/hint` — progressive hint at level 1 (conceptual), 2 (approach), or 3 (pseudocode). Max 3 levels.
5. `POST /api/coding/evaluate-graded` — Qwen scores each rubric criterion, returns `{ score, letter_grade, status, breakdown[], feedback, hint }`. Auto-fallback to `llama-3.3-70b-versatile` if Qwen fails JSON validation.

**Letter grade mapping:** A 90+, A− 87+, B+ 83+, B 80+, B− 77+, C+ 73+, C 70+, C− 67+, D 60+, F <60.

### SharedSessionStore
Singleton (`session_store.py`) shared across all AI subsystems. Stores `UnifiedStudentContext` (profile state + live session state) per `session_id`. Thread-safe. Redis-ready (set `REDIS_URL` to switch backend). Used by: Tutor, Intent, Profiler, FER/SER, Slides.

### Audio2Face (A2F) Integration
- `a2f_client.py` — gRPC client connecting to NVIDIA Audio2Face-3D NIM at `A2F_GRPC_HOST:A2F_GRPC_PORT` (default `localhost:52000`).
- `GET /a2f/health` — checks gRPC channel readiness (2s timeout).
- Frontend `Nova3DAvatar.tsx` renders a MetaHuman `.gltf` mesh with blendshapes driven by A2F data.
- If A2F is unavailable, the avatar falls back to a fallback viseme animation sequence.

### TTS Voices
Default voice changed from `en-US-JennyNeural` to **`en-US-AndrewMultilingualNeural`**. Available voices: jenny, aria, guy, andrew, ava. Aria supports emotional delivery styles (cheerful, sad, angry, excited, friendly, hopeful, empathetic).

### ASR Flow
1. Audio file uploaded (wav/mp3/m4a/ogg/flac)
2. Whisper transcribes (16kHz mono)
3. Returns: `{ transcription, language, inference_time_seconds, filename }`

### Tutor (Dr. Nova) Flow
1. `POST /tutor/start` with `{ lesson_title, subtopics[] }` → `session_id`
2. `POST /tutor/continue` with `{ session_id, include_audio: true }` repeatedly
3. Each chunk: `{ text, audio_base64 (MP3 base64), progress, is_finished, subtopic }`
4. `POST /tutor/ask` for mid-lecture questions
5. `POST /tutor/stop` on unmount

### Intent Classification (5 classes)
- `On-Topic Question` — RAG + tutor
- `Off-Topic Question` — redirect
- `Emotional-State` — encouragement
- `Pace-Related` — guide to Pause/Next
- `Repeat/clarification` — replay audio or re-explain

**Weights file** `prod_tinybert.pt` / `best_model.pt` — not in git, must be placed in `ai_service/intent_model/` manually.

### RAG Flow
1. `POST /rag/ask` with `{ question, topic, top_k }`
2. Embeds question with `sentence-transformers/all-MiniLM-L6-v2`
3. ChromaDB retrieves top-k chunks
4. Ollama LLM generates grounded answer
5. Returns `{ answer, sources: [{ book, page_start, page_end, topic, relevance_score }] }`

**Books indexed (1,462 chunks):** Problem Solving with Algorithms and Data Structures, Think Python 2nd Edition, Python Learn, SciPy Lectures.

---

## Frontend (React 18 + TypeScript + Vite)

### Layout
```
frontend/src/
├── main.tsx
├── App.tsx               ← RouterProvider + Toaster
├── routes.tsx            ← All routes
├── index.css
├── contexts/
│   ├── AuthContext.tsx
│   └── ThemeContext.tsx
├── layouts/
│   ├── StudentLayout.tsx
│   ├── AdminLayout.tsx
│   └── InstructorLayout.tsx
├── components/
│   ├── TopNav.tsx
│   ├── NotificationBell.tsx  ← Bell + unread badge; marks all read on open, individual on click
│   ├── Header.tsx
│   ├── SessionControls.tsx
│   ├── SlidesViewer.tsx
│   ├── GeneratedSlidesViewer.tsx
│   ├── VisualRenderer.tsx
│   ├── CompactTutor.tsx      ← Dr. Nova AI tutor panel
│   ├── Nova3DAvatar.tsx      ← Three.js MetaHuman avatar with A2F blendshapes (replaces NovaAvatar)
│   ├── CodePanel.tsx
│   ├── CircularProgress.tsx
│   ├── RequireAuth.tsx
│   ├── RequirePathway.tsx    ← Guards LiveSession; redirects to assessment if !is_pathway_ready
│   └── ui/                  ← shadcn/ui components
├── pages/
│   ├── auth/Login.tsx
│   ├── admin/
│   │   ├── AdminDashboard.tsx
│   │   ├── AdminStudents.tsx
│   │   └── AdminCourseEditor.tsx
│   ├── instructor/
│   │   └── InstructorDashboard.tsx
│   ├── shared/NotFound.tsx
│   ├── Courses.tsx
│   ├── CourseDetail.tsx
│   ├── Assessment.tsx
│   ├── Profile.tsx
│   └── student/
│       ├── Dashboard.tsx
│       ├── LiveSession.tsx       ← Slides + CompactTutor; on complete → LessonPractice
│       ├── PracticeArea.tsx      ← Two-dropdown topic selector + Monaco + graded evaluation
│       ├── LessonPractice.tsx    ← Lesson-end coding practice (Skip or Submit for bonus XP)
│       ├── Leaderboard.tsx
│       └── CoursePathway.tsx
└── services/
    ├── api.ts
    ├── auth.ts
    ├── courses.ts
    ├── lessons.ts
    ├── progress.ts       ← includes reportPracticeCompletion()
    ├── gamification.ts
    ├── notifications.ts  ← getNotifications, markNotificationRead, markAllNotificationsRead
    ├── profile.ts
    ├── assessments.ts
    ├── coding.ts         ← generateQuestion, evaluateCode, getRubric, evaluateCodeGraded, getHint
    ├── tutor.ts
    ├── pathway.ts
    ├── emotionFusion.ts  ← Client-side FER+SER fusion with LLM arbitration fallback
    └── admin.ts
```

### Routes

```
/login                                     → Login (public)
/                                          → Redirect to /dashboard
/dashboard                                 → Student dashboard
/courses                                   → Course catalog
/courses/:courseId                         → Course detail
/courses/:courseId/assessment              → Placement assessment
/course/:courseId/pathway                  → Personalized course pathway
/course/:courseId/lesson/:lessonId         → Live session (RequirePathway guard)
/course/:courseId/lesson/:lessonId/practice → Lesson-end coding practice
/practice                                  → Coding practice arena (manual topic selection)
/practice/:topic                           → Coding practice arena (auto-generates for topic)
/leaderboard                               → Top 20 leaderboard
/profile                                   → User profile & settings
/admin                                     → Admin dashboard
/admin/students                            → All students list
/admin/courses/:courseId/editor            → Module/lesson content editor
/instructor                                → Instructor dashboard
```

- Student routes: `<RequireAuth allowedRoles={["student"]}>` inside `StudentLayout`
- Admin routes: `<RequireAuth allowedRoles={["admin"]}>` inside `AdminLayout`
- Instructor routes: `<RequireAuth allowedRoles={["instructor"]}>` inside `InstructorLayout`
- `LiveSession` additionally wrapped in `<RequirePathway>` — redirects to assessment if `enrollment.is_pathway_ready` is `false`
- `PathwaySession.tsx` has been removed; pathway sessions are now handled within `LiveSession`

---

### Key Component Behaviours

#### `RequirePathway.tsx`
- Checks `enrollment.is_pathway_ready` for the current `courseId`
- If `false` or no enrollment found → redirects to `/courses/:courseId/assessment`
- Shows a spinner while checking

#### `Nova3DAvatar.tsx`
- Renders a MetaHuman `.gltf` mesh loaded from `/static/metaHumanHead_52shapekeys_01.gltf`
- Driven by blendshape data from Audio2Face NIM when available
- Fallback: client-side viseme animation sequence synchronized to the audio element
- Emotion mapping: student emotion (e.g. `frustrated`) → avatar response emotion (e.g. `encouraging`) → blendshape weights
- Props: `audioRef`, `emotion?`, `blendshapeData?`, `size?`, `isFloating?`

#### `NotificationBell.tsx`
- Polls `GET /notifications/` every 60s
- On bell click (open): auto-calls `markAllNotificationsRead()` if there are unread notifications
- On individual notification click: calls `markNotificationRead(id)` for that notification
- Unread = bold title + blue dot indicator; read = dimmed (opacity 0.7)

#### `PracticeArea.tsx`
- **Topic selector:** Two dropdowns (Category → Topic) with Generate button. 5 categories: Standard Coding Topics, Data Structures, Advanced Algorithmic Topics, Data Structures & Algorithms, Machine Learning Fundamentals.
- After `generateQuestion()`: loads rubric in background via `rubricRef`
- **Hint button:** 3 levels (Get Hint Level 1/2/3 → All hints used). Amber callout box per hint.
- **Score display:** `text-4xl font-extrabold` colored number (no box/frame) + letter grade + Pass/Needs Work
- **Expandable breakdown:** per-criterion score bar + comment
- Submit always re-enabled after result (no `|| !!result` in disabled prop)
- Topic-specific guidance in prompt prevents off-topic questions (e.g. "Linear Regression" always gets slope/intercept or MSE problems)
- Question history tracked per topic in-process (max 10) to prevent repeats

#### `LessonPractice.tsx`
- Route: `/course/:courseId/lesson/:lessonId/practice`
- Receives `{ nextLessonId, courseId, lessonTitle }` via router `state`
- Auto-generates question on mount using `lessonTitle` as topic
- **"Skip & Continue"** → navigates to next lesson (or dashboard)
- **"Submit & Earn XP"** → grades code; on score ≥ 60 calls `reportPracticeCompletion()` → toast with XP earned → navigates next
- Resubmission always enabled

#### `LiveSession.tsx`
- On "Complete & Next": navigates to `/course/:courseId/lesson/:lessonId/practice` with `{ nextLessonId, courseId, lessonTitle }` state
- `PathwaySession` functionality merged into `LiveSession` — no separate PathwaySession page
- Conversational agent (CompactTutor) reads current slide content from `SharedSessionStore` for context-aware answers

#### `CompactTutor.tsx`
- Uses `Nova3DAvatar` (3D MetaHuman) instead of the old `NovaAvatar`
- Session state synced to `SharedSessionStore` via `PATCH /session/{session_id}` on each slide change
- "Practice Now" button (when lecture finishes) → navigates to `/practice/:lessonTitle`

#### `emotionFusion.ts`
- Client-side: FER + SER agreement → use directly; conflict → `POST /profiler/fuse-emotions` (3s timeout); one missing → use whichever is present; both missing → neutral
- When `session_id` present, always logs to `/profiler/fuse-emotions` even on agreement

---

### Design System (Tailwind conventions)

| Element | Class pattern |
|---------|--------------|
| Primary gradient button | `bg-gradient-to-r from-primary to-secondary text-white rounded-xl` |
| Secondary gradient button | `bg-gradient-to-r from-secondary to-accent text-white rounded-xl` |
| Card | `bg-card rounded-2xl border border-border shadow-sm` |
| Section heading | `text-lg font-semibold` |
| Muted label | `text-sm text-muted-foreground` |
| Loading spinner | `<Loader2 size={40} className="animate-spin text-secondary" />` |
| Error/success | Sonner toast (`toast.error()`, `toast.success()`) — never `alert()` |
| Score color | 90+: emerald `#10b981`, 80+: blue `#3b82f6`, 70+: indigo `#6366f1`, 60+: amber `#f59e0b`, <60: rose `#ef4444` |

**Sonner `<Toaster />` is mounted in `App.tsx`.**

---

## User Flow (End-to-End)

```
/login → role-based redirect
  ├── student → /dashboard
  └── admin   → /admin

/courses → /courses/:courseId
  ├── [unenrolled] "Start Assessment & Enroll"
  │     → POST /courses/enrollments/
  │     → /courses/:courseId/assessment (6 MCQ, AI or static fallback)
  │     → PATCH enrollment.placement_score + is_pathway_ready=true
  │     → "Begin Learning" → /dashboard
  └── [enrolled + is_pathway_ready] "Continue Learning"
        → /course/:courseId/lesson/:lessonId  (RequirePathway passes)

Live lesson:
  Slides + Dr. Nova (Nova3DAvatar) + CompactTutor
  FER/SER → emotionFusion → profiler/fuse-emotions
  Complete & Next → /course/:courseId/lesson/:lessonId/practice
    ├── Skip → next lesson
    └── Submit (score ≥ 60) → XP awarded → next lesson

Coding practice (/practice):
  Category dropdown → Topic dropdown → Generate Question
  Get hints (up to 3 levels) → Submit → 0–100 score + breakdown

Admin:
  /admin → stats + course CRUD → /admin/courses/:id/editor (module/lesson CRUD)
  /admin/students → all students with gamification data
```

---

## Known Issues / Implementation Notes

- `total_lessons_count` on `Course` model is a stored field (default 0) that never auto-updates. The serializer overrides with a computed `SerializerMethodField`. Never set it manually.
- `is_pathway_ready` must be `True` before a student can access `LiveSession`. It is set after placement assessment completes.
- Tutor sessions are **in-memory** in `tutor_service.py` — lost on AI service restart. `SharedSessionStore` is also in-memory by default (set `REDIS_URL` for persistence).
- A2F (Audio2Face) is optional. Without it, `Nova3DAvatar` uses client-side fallback visemes. `/a2f/health` returns `connected: false` when unreachable.
- TTS default voice is now `en-US-AndrewMultilingualNeural` (was `en-US-JennyNeural`).
- `CODING_USE_T5=true` only affects question generation — rubric/evaluation/hints always use Qwen/Groq.
- Question history is in-process per topic (resets on AI service restart) — prevents repeats within a session.
- `PathwaySession.tsx` has been removed. Pathway session content is now served through `LiveSession`.
- `NovaAvatar.tsx` has been removed. Replaced by `Nova3DAvatar.tsx` (Three.js + MetaHuman gltf).
- `emotionLogger.ts` has been removed. Replaced by `emotionFusion.ts`.
- Intent model weights (`best_model.pt`) are not in git — place in `ai_service/intent_model/` manually.
- RAG ChromaDB index is not in git — run `python scripts/run_indexer.py` from `rag_pipeline/`.
- **Dark mode:** persists in `localStorage` under key `'theme'`; CSS variables switch via `.dark {}` class on `<html>`.
- Run `python manage.py seed_achievements` once after deployment to populate achievements.
- TopNav gradient classes use inline `style` (not Tailwind dynamic classes) to avoid purge issues.
- `LiveSession` route: `/course/:courseId/lesson/:lessonId` (no `s` on course). `CourseDetail` route: `/courses/:courseId` (with `s`). Keep consistent.

---

## Tech Stack Summary

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend framework | React | 18.3.1 |
| Frontend build | Vite | 6.3.5 |
| Frontend routing | React Router | 7.13.1 |
| Frontend HTTP | Axios | 1.13.5 |
| Frontend UI | Tailwind CSS + Radix UI (shadcn/ui) | — |
| Frontend 3D | Three.js | — |
| Frontend charts | Recharts | 2.15.2 |
| Frontend code editor | Monaco Editor | 4.7.0 |
| Frontend icons | Lucide React | 0.487.0 |
| Frontend toasts | Sonner | 2.0.3 |
| Backend framework | Django + DRF | 4.2 |
| Backend auth | Token Authentication | — |
| Database | Supabase (PostgreSQL) | 15 |
| AI service | FastAPI + Uvicorn | 0.104+ |
| LLM (coding/rubric/hints) | Groq — qwen/qwen3-32b (fallback: llama-3.3-70b-versatile) | — |
| LLM (tutor + RAG) | Ollama Cloud (configurable) | — |
| Code generation (legacy) | Custom T5 (LeetCode fine-tuned) | — |
| Intent classification | Custom TinyBERT (fine-tuned, 5 classes) | — |
| RAG vector store | ChromaDB | — |
| RAG embeddings | sentence-transformers/all-MiniLM-L6-v2 | — |
| ASR | OpenAI Whisper | tiny model |
| TTS | edge-tts (Microsoft Neural Voice) | 6.1+ |
| 3D Avatar | Three.js + MetaHuman gltf + A2F NIM gRPC | — |
| Session state | SharedSessionStore (in-memory, Redis-ready) | — |
| Caching | LocMemCache (default); Redis if REDIS_URL set | — |
