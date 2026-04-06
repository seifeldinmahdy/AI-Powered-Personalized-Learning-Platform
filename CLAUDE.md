# AI-Powered Personalized Learning Platform — CLAUDE.md

This file is the authoritative reference for Claude Code when working on this project.
It covers architecture, all services, data models, API contracts, frontend structure, and current implementation status.

---

## Project Overview

An AI-driven e-learning platform that delivers personalized learning pathways.
Students take a **placement assessment** before starting a course, and the system adapts content difficulty and progression based on their performance.
The platform includes interactive slide-based lessons, an AI tutor (Dr. Nova) with real-time emotion tracking and adaptive voice prosody, a coding practice arena, and a gamification layer.

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
                    ┌────────┼────────┬──────────┬──────────┬────────────┐
                    ▼        ▼        ▼          ▼          ▼            ▼
               Whisper    Groq API  Custom T5  Ollama     edge-tts    Profiler
               (ASR)    (llama-3.1) (LeetCode) (Dr. Nova) (TTS)     (Groq LLM)
```

**Emotion pipeline (real-time during sessions):**
```
Webcam (FER)  ──┐
                ├─→ fuseEmotions() ──→ fusedEmotion state ──→ Dr. Nova (tone/prosody)
Microphone (SER)┘                                          ──→ NovaAvatar (expression)
                                                           ──→ emotionLogger (in-memory cache)
                                                                   │
                                                           session end → profiler LLM
                                                                   │
                                                           POST /progress/learning-profile/
                                                           (overwrites single row per student)
```

**Supporting infra (docker-compose.yml):** PostgreSQL 15 (port 5432), MongoDB 6 (port 27017), Redis 7 (port 6379).

---

## How to Start Servers

```bash
# Frontend
cd frontend && npm run dev          # http://localhost:3000

# Backend
cd backend
source venv/Scripts/activate        # Windows: .venv\Scripts\activate
python manage.py runserver          # http://localhost:8000

# AI Service
cd ai_service
source venv/Scripts/activate
uvicorn main:app --port 8001 --reload   # http://localhost:8001
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
OLLAMA_MODEL=llama3.2                # or whichever model is deployed
OLLAMA_API_KEY=...                   # Ollama Cloud API key
```

### Frontend (`frontend/.env`)
```
VITE_API_URL=http://localhost:8000/api
VITE_AI_URL=http://127.0.0.1:8001
VITE_AI_SERVICE_URL=http://localhost:8001
```

---

## Backend (Django REST Framework)

### Project Layout
```
backend/
├── config/
│   ├── settings.py       ← Django config, DB, DRF, CORS
│   ├── urls.py           ← Root URL routing
│   ├── asgi.py / wsgi.py
└── apps/
    ├── core/             ← Health check
    ├── users/            ← Auth, profiles, preferences
    ├── courses/          ← Courses, modules, lessons, enrollments
    ├── progress/         ← Lesson completions, activity logs, AI chat logs, learning profiles
    └── gamification/     ← Achievements, daily study stats
```

### Settings Highlights
- **Custom user model:** `apps.users.User`
- **Auth:** `rest_framework.authtoken` (Token authentication)
- **Pagination:** `PageNumberPagination`, page_size = 20
- **CORS:** Allowed for `http://localhost:3000`, `http://localhost:5173`

---

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

#### Serializers
- `UserSerializer` → fields: id, username, email, role, bio, created_at
- `StudentProfileSerializer` → all StudentProfile fields (level, XP, streaks, etc.)
- `UserPreferencesSerializer` → email_notifications, ai_tutor_voice_enabled, study_reminders

---

### App: `courses`

#### Models
| Model | Key Fields |
|-------|-----------|
| `Course` | `title`, `description`, `instructor` (FK→User), `syllabus` (JSON), `difficulty` (Beginner/Intermediate/Advanced), `status` (Draft/Published/Archived), `price`, `tags` (array), `total_lessons_count` (stored int, computed by serializer), `avg_rating` |
| `Module` | `course` (FK), `title`, `module_order` |
| `Lesson` | `module` (FK), `title`, `lesson_order` |
| `Slide` | `lesson` (FK), `content_json`, `slide_order` |
| `CodeChallenge` | `lesson` (FK), `problem_text`, `starter_code`, `solution_code`, `test_cases_json`, `hint_text` |
| `Enrollment` | `student` (FK→User), `course` (FK), `placement_score`, `current_lesson` (FK→Lesson), `current_pathway` (JSON), `progress_percentage`, `current_score`, `is_paid` |

**Important:** `total_lessons_count` on the `Course` model is a stored `IntegerField(default=0)` that doesn't auto-update. The `CourseSerializer` overrides it with a `SerializerMethodField` that does `Lesson.objects.filter(module__course=obj).count()`.

#### Endpoints (`/api/courses/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/courses/` | List courses (search, filter by difficulty/status, ordering) |
| GET | `/courses/:id/` | Course detail (includes syllabus) |
| GET | `/modules/?course_id=X` | Modules for a course (paginated) |
| GET | `/lessons/?module_id=X` | Lessons for a module (paginated) |
| GET | `/lessons/:id/` | Lesson detail with nested slides + code_challenges |
| GET | `/slides/?lesson_id=X` | Slides for a lesson |
| GET | `/code-challenges/?lesson_id=X` | Code challenges (student-safe: no solution_code) |
| GET/POST | `/enrollments/` | List / create enrollments |
| PATCH | `/enrollments/:id/` | Update enrollment (placement_score, current_lesson, etc.) |
| POST | `/coding/evaluate/` | Bridge to AI service for code evaluation |

**Paginated responses** (`/modules/`, `/lessons/`, `/enrollments/`): `{ count, next, previous, results: [...] }`

The frontend services (`getModules`, `getLessons`) handle both array and paginated formats:
```ts
const data = response.data;
return Array.isArray(data) ? data : data.results ?? [];
```

---

### App: `progress`

#### Models
| Model | Key Fields |
|-------|-----------|
| `LessonCompletion` | `enrollment` (FK), `lesson` (FK), `status` (Started/In Progress/Completed), `score`, `completed_at` |
| `SystemActivityLog` | `user` (FK), `action_type`, `target_course` (FK), `created_at` |
| `AIChatLog` | `user` (FK), `lesson` (FK), `user_audio_url`, `transcript_text`, `ai_response_text` |
| `StudentLearningProfile` | `student` (1-1→User), `last_updated`, `sessions_count`, `profile_summary` (text), `profile_data` (JSON) |

**Important — Data Persistence Model:**
- **Session interactions are NEVER written to the database.** All emotion events, transcript chunks, and per-interaction data live ONLY in the in-memory `emotionLogger` cache on the frontend.
- At session end, the in-memory session log is sent to the profiler LLM (Groq), which synthesizes it into a concise learning profile.
- That single `StudentLearningProfile` row is the ONLY thing persisted per student — it is overwritten (not appended) after each session.
- `profile_summary`: plain-English paragraph (max 5 sentences) that Dr. Nova reads at session start for personalization.
- `profile_data`: structured JSON with keys: `learning_style_signals`, `engagement_patterns`, `emotional_tendencies`, `recommended_approaches`, `topics_of_difficulty`, `topics_of_strength`.
- There is **no** `StudentSessionProfile` model — it was removed. Session data is ephemeral.

#### Endpoints (`/api/progress/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/lesson-completions/?enrollment_id=X` | List completions for enrollment |
| POST | `/lesson-completions/` | Create completion record |
| POST | `/lesson-completions/:id/complete/` | Mark lesson as completed |
| PATCH | `/lesson-completions/:id/` | Update completion status/score |
| GET | `/activity-logs/` | User activity history |
| GET | `/ai-chat-logs/?lesson_id=X` | AI chat history for a lesson |
| GET | `/learning-profile/` | Get the student's single learning profile (returns 404 if none) |
| POST | `/learning-profile/` | Create or overwrite the student's learning profile |

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
| GET/POST | `/daily-stats/` | Study time log (user-scoped) |

---

## AI Service (FastAPI)

### Layout
```
ai_service/
├── main.py               ← FastAPI app, CORS, router inclusion
├── routers/
│   ├── health.py         ← GET /health
│   ├── asr.py            ← POST /asr/transcribe
│   ├── coding.py         ← POST /api/coding/generate, /api/coding/evaluate
│   ├── tutor.py          ← POST /tutor/start, /tutor/continue, /tutor/ask, /tutor/stop
│   ├── tts.py            ← POST /tts/synthesize
│   ├── fer.py            ← POST /fer/predict (Facial Emotion Recognition)
│   ├── ser.py            ← POST /ser/predict (Speech Emotion Recognition)
│   ├── profiler.py       ← POST /profiler/fuse-emotions, /profiler/update
│   └── intent.py         ← POST /intent/classify
├── services/
│   ├── asr_service.py    ← OpenAI Whisper (tiny model default)
│   ├── coding_service.py ← Custom T5 model + Groq for code gen
│   ├── evaluator.py      ← Groq llama-3.1-8b for code feedback
│   ├── tutor_service.py  ← Ollama Cloud LLM (Dr. Nova persona), in-memory sessions, emotion-adaptive TTS
│   ├── tts_service.py    ← edge-tts (Microsoft Neural Voice, en-US-AndrewMultilingualNeural)
│   └── profiler_service.py ← Groq-powered educational psychologist LLM for profile synthesis
├── schemas/
│   └── coding.py         ← TopicRequest, SubmitRequest pydantic models
└── models/
    └── clean_question_model/   ← Custom fine-tuned T5 (LeetCode problems)
```

### Endpoints
| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/health` | Health check | None |
| POST | `/asr/transcribe` | Audio → text (Whisper) | None |
| GET | `/asr/health` | Whisper model status | None |
| POST | `/api/coding/generate` | Generate coding problem from topic | None |
| POST | `/api/coding/evaluate` | Evaluate student code submission | None |
| POST | `/api/assessments/generate` | Generate MCQ placement questions | None (not yet implemented — frontend falls back to static bank) |
| POST | `/tutor/start` | Start tutor session → `{ session_id }` | None |
| POST | `/tutor/continue` | Get next lecture chunk → `{ text, audio_base64, progress, is_finished, subtopic }` | None |
| POST | `/tutor/ask` | Ask Dr. Nova a question → `{ answer, audio_base64 }` | None |
| POST | `/tutor/stop` | End tutor session | None |
| GET | `/tutor/status/{session_id}` | Get session status | None |
| GET | `/tutor/health` | Tutor service health | None |
| POST | `/tts/synthesize` | Text → MP3 audio (edge-tts) | None |
| POST | `/fer/predict` | Image frame → facial emotion label | None |
| POST | `/ser/predict` | Audio → speech emotion label | None |
| POST | `/profiler/fuse-emotions` | Fuse FER + SER labels → single emotion | None |
| POST | `/profiler/update` | Synthesize session log into learning profile | None |
| POST | `/intent/classify` | Text → intent classification | None |

### Code Generation Flow
1. Custom T5 model (`clean_question_model`) generates the problem text from topic
2. Groq API (`llama-3.1-8b-instant`) generates starter code for the problem
3. Returns: `{ question: str, starter_code: str }`

### Code Evaluation Flow
1. Groq API evaluates student code against the problem
2. Returns: `{ status: "Pass" | "Needs Work", feedback: str }`

### ASR Flow
1. Audio file uploaded (wav/mp3/m4a/ogg/flac)
2. Whisper model transcribes (16kHz mono)
3. Returns: `{ transcription, language, inference_time_seconds, filename }`

### Tutor (Dr. Nova) Flow
1. Client calls `POST /tutor/start` with `{ lesson_title, subtopics[] }` → gets `session_id`
2. Client calls `POST /tutor/continue` with `{ session_id, include_audio: true, fused_emotion?: string }` repeatedly
3. Each chunk returns `{ text, audio_base64 (MP3, base64), progress (0–100), is_finished, subtopic }`
4. Client decodes base64 → Blob → plays through `<audio>` DOM element
5. When `is_finished: true`, lecture is complete
6. Client may call `POST /tutor/ask` at any time to ask questions mid-lecture (also accepts `fused_emotion`)
7. Client calls `POST /tutor/stop` on component unmount to free session memory

**Emotion-adaptive TTS:** The `fused_emotion` parameter controls voice prosody:
| Emotion | Rate | Pitch |
|---------|------|-------|
| bored | +15% | +5Hz |
| confused | -15% | -3Hz |
| anxious | -10% | -5Hz |
| happy/excited | +10% | +3Hz |
| frustrated | -10% | -3Hz |
| neutral (default) | +0% | +0Hz |

**Audio autoplay note:** Browser autoplay policy blocks `audio.play()` after async calls. The "Start Lecture" button unlocks the `<audio>` element synchronously via a click gesture before any async work begins.

### TTS Flow
1. Text sent to `POST /tts/synthesize`
2. `edge-tts` synthesizes using Microsoft Neural Voice (default: `en-US-AndrewMultilingualNeural`, no API key required)
3. Rate and pitch are configurable parameters (defaults: `+0%` rate, `+0Hz` pitch)
4. Returns MP3 bytes (used internally by tutor service)

### Profiler Flow (Session End)
1. Frontend sends the in-memory session log (from `emotionLogger`) + existing profile to `POST /profiler/update`
2. Groq LLM (acting as educational psychologist) synthesizes the session data into structured JSON
3. Uses `response_format={"type": "json_object"}` for guaranteed JSON output
4. Robust parsing: strips markdown fences, try/catch with raw output logging on failure
5. Returns `{ profile_summary, profile_data, sessions_count }`
6. Frontend POSTs this to `POST /progress/learning-profile/` (Django) to overwrite the single profile row

### Emotion Fusion Flow
1. FER (facial) and SER (speech) predictions sent to `POST /profiler/fuse-emotions`
2. Groq LLM fuses the two signals into a single emotion label
3. Returns `{ fused_emotion: string }`
4. Frontend stores this in React state (`fusedEmotion`) and passes to Dr. Nova and NovaAvatar

---

## Frontend (React 18 + TypeScript + Vite)

### Layout
```
frontend/src/
├── main.tsx              ← React entry point
├── App.tsx               ← RouterProvider + Toaster
├── routes.tsx            ← All routes
├── index.css
├── styles/
│   └── globals.css       ← Global styles + NovaAvatar CSS animations (novaFloat, novaRingSpin, novaParticle, novaEmotionPop)
├── contexts/
│   └── AuthContext.tsx   ← User, isAuthenticated, login/logout
├── layouts/
│   ├── StudentLayout.tsx ← TopNav + Outlet (flex-col)
│   └── AdminLayout.tsx   ← TopNav (admin variant) + Outlet
├── components/
│   ├── TopNav.tsx        ← Horizontal navbar (replaces sidebar)
│   ├── Header.tsx        ← Per-page subheader
│   ├── SessionControls.tsx ← Prev/Next/Complete bar in LiveSession
│   ├── SlidesViewer.tsx  ← Slide display component (accepts isFullscreen + onFullscreenToggle props)
│   ├── CompactTutor.tsx  ← Dr. Nova AI tutor panel (supports floating mode for fullscreen)
│   ├── NovaAvatar.tsx    ← Canvas2D animated AI face with spring physics, viseme lip-sync, emotion expressions
│   ├── CodePanel.tsx     ← Monaco editor panel (used in PracticeArea)
│   ├── CircularProgress.tsx
│   └── ui/               ← shadcn/ui components (Radix UI + Tailwind)
├── pages/
│   ├── auth/Login.tsx
│   ├── admin/AdminDashboard.tsx
│   ├── shared/NotFound.tsx
│   ├── Courses.tsx        ← Course catalog with filters
│   ├── CourseDetail.tsx   ← Course overview, syllabus, module accordion, CTA
│   ├── Assessment.tsx     ← Placement quiz (6 MCQ, results with tier)
│   └── student/
│       ├── Dashboard.tsx
│       ├── LiveSession.tsx ← Slides + AI tutor + fullscreen + emotion tracking
│       └── PracticeArea.tsx ← Topic selector + Monaco + AI feedback
└── services/
    ├── api.ts            ← Axios instance, auth interceptor, enroll, getEnrollments
    ├── auth.ts           ← login, signup, logout
    ├── courses.ts        ← getCourses, getCourseById
    ├── lessons.ts        ← getModules, getLessons, getLesson (paginated-aware)
    ├── progress.ts       ← getLessonCompletions, createLessonCompletion, markLessonComplete
    ├── gamification.ts   ← getMyAchievements, getDailyStats
    ├── profile.ts        ← getProfile, getStudentProfile, getPreferences, updatePreferences
    ├── assessments.ts    ← generateAssessmentQuestions (AI + static fallback), updatePlacementScore
    ├── coding.ts         ← generateQuestion (FastAPI), evaluateCode (Django bridge)
    ├── tutor.ts          ← startTutorSession, continueTutorSession, askTutor, stopTutorSession
    ├── emotionLogger.ts  ← In-memory emotion event cache (logEmotionEvent, getSessionLog, getRecentFusedEmotion, clearSessionLog)
    └── emotionFusion.ts  ← fuseEmotions() — calls POST /profiler/fuse-emotions
```

---

### Routes

```tsx
/login                         → Login page (public)
/                              → Redirect to /dashboard
/dashboard                     → Student dashboard
/courses                       → Course catalog
/courses/:courseId             → Course detail (CourseDetail.tsx)
/courses/:courseId/assessment  → Placement assessment (Assessment.tsx)
/course/:courseId/lesson/:lessonId → Live session (LiveSession.tsx)
/practice                      → Coding practice arena (manual topic selection)
/practice/:topic               → Coding practice arena (auto-generates question for given topic)
/profile                       → User profile & settings
/admin                         → Admin dashboard (admin role only)
```

All student routes are wrapped in `<RequireAuth allowedRoles={["student"]}>`.

---

### Auth Context

```ts
interface User {
  id: number;
  username: string;
  email: string;
  full_name?: string;
  role: 'student' | 'admin';
}
```

Stored in `localStorage`: `"auth_user"` (JSON), `"token"` (string).
The axios instance in `api.ts` reads `"token"` and sets `Authorization: Token <token>` on every request.

---

### Key Component Behaviours

#### `TopNav.tsx`
- `variant="student"` → nav links: Dashboard, Courses, Practice, Profile; brand gradient blue→purple
- `variant="admin"` → nav links: Overview, Courses; brand gradient rose→indigo
- Active link highlighted with gradient pill
- User avatar dropdown: Profile + Logout

#### `CourseDetail.tsx` (`/courses/:courseId`)
- Fetches course, modules, enrollments in parallel
- If enrolled: fetches `getLessonCompletions` to show ✅/🔒 per lesson
- Module accordion lazy-loads lessons on expand
- CTA card: "Start Assessment & Enroll" (unenrolled) or "Continue Learning" (enrolled)
- "Start Assessment & Enroll" → `POST /courses/enrollments/` → navigate to `/courses/:courseId/assessment`
- "Continue Learning" → navigates to `current_lesson` or fetches first lesson of first module

#### `Assessment.tsx` (`/courses/:courseId/assessment`)
- Receives `{ enrollmentId, courseTitle }` via router state
- Calls `generateAssessmentQuestions(courseTitle, 6)` on mount
- Falls back to static 8-question bank if AI endpoint unavailable
- Results screen shows score %, tier label (Beginner <40%, Intermediate 40–74%, Advanced ≥75%)
- On finish: `PATCH /courses/enrollments/:id/` with `placement_score`

#### `LiveSession.tsx` (`/course/:courseId/lesson/:lessonId`)
- Layout: **SlidesViewer (70%)** | **CompactTutor (30%)** — no code editor
- On load: fetches all modules + all lessons for the course to build ordered lesson list
- Prev button: goes to previous slide; if first slide → navigate to previous lesson
- Next button: goes to next slide; if last slide → navigate to next lesson
- "Complete & Next" button: marks lesson complete, navigates to next lesson (or dashboard with toast on last lesson)
- `backLink` points to `/courses/:courseId` (not dashboard)
- **Fullscreen mode:** Controlled by LiveSession (not SlidesViewer). The entire content area goes fullscreen. In fullscreen, CompactTutor becomes a floating overlay panel on the left side (300px wide, max 50vh tall, `position: absolute`, `left: 12, top: 12`). SlidesViewer gets `paddingLeft: 324px` to avoid overlap.
- **Emotion tracking:** Camera toggle button (bottom-right pill). When enabled, FER polls webcam every few seconds. SER runs on each voice recording. Both fused via `POST /profiler/fuse-emotions` into `fusedEmotion` state, which is passed to CompactTutor and NovaAvatar.

#### `CompactTutor.tsx` (Dr. Nova panel in LiveSession)
- Fully wired to AI tutor service (not a static mockup)
- "Start Lecture" button unlocks browser audio policy synchronously, then starts the session
- Persistent `<audio>` DOM element (ref) — not recreated between chunks
- Lecture progresses chunk by chunk; each chunk has text transcript + MP3 audio
- Play/Pause: calls `audio.pause()` / `audio.play()` on the same element (position preserved)
- Mute/Unmute: sets `audio.muted` property (no restart, no position reset)
- "Next" button: skips current chunk audio and fetches the next chunk
- When `is_finished: true`, a **"Practice Now"** button appears — navigates to `/practice/:lessonTitle` with `{ state: { topic: lessonTitle } }` so PracticeArea auto-generates a coding question for that lesson's topic
- **Floating mode (`isFloating` prop):** When fullscreen is active, the panel positions itself `absolute` left:12, top:12, width:300, maxHeight:50vh with rounded corners and backdrop blur. Avatar shrinks to 56px. Transcript scrolls vertically within the constrained height.

#### `NovaAvatar.tsx` (Animated AI Face)
- **Canvas2D** rendered at 60fps via `requestAnimationFrame` — NOT SVG or CSS transitions
- **Spring physics**: Every animated property (eyebrows, eye openness, pupil size, mouth shape, head tilt, look direction) uses a custom `Spring` class with stiffness/damping for organic movement
- **Lip sync**: Web Audio `AnalyserNode` reads frequency data from the `<audio>` element. Mouth cycles through 6 viseme shapes (closed, slightly parted, medium open, tall open, wide, O-shape) at a rate determined by audio amplitude
- **Emotion-driven expressions**: 13 emotion states mapped to unique visual properties (eye openness, pupil size, brow positions, mouth smile/frown, color palette). Emotions: happy, excited, sad, angry, frustrated, confused, surprised, fear, anxious, bored, disgust, calm
- **Eye look-around**: Pupils drift to random positions every 1.5–4.5s with spring easing
- **Natural blinks**: Random blink intervals (2–6s), 150ms blink duration
- **Head tilt**: Subtle random rotation applied via canvas transform
- **Particles**: 16 floating particles orbit the face, brightening with speech amplitude
- **Holographic design**: Dark faceplate (#0B0F2E → #111640), glowing wireframe eye sockets, spinning accent arc, circuit trace accents
- **Color transitions**: Smooth RGB lerp between emotion color palettes (~0.5s transition)
- **Overflow**: Container has `overflow: hidden` to prevent canvas glow from bleeding

#### `Courses.tsx` (`/courses`)
- Both enrolled ("Continue Learning") and unenrolled ("View Course") cards link to `/courses/:courseId`
- Cards have `hover:-translate-y-1` lift effect
- Stats row shows lessons count + estimated duration (lessons × 30 min)

#### `PracticeArea.tsx` (`/practice` and `/practice/:topic`)
- Left panel (35%): topic category pills → Generate Question button → problem display → AI feedback
- Right panel (65%): Monaco editor (Python, dark theme) + Submit Code button
- Generate: FastAPI `POST /api/coding/generate`
- Submit: Django `POST /courses/coding/evaluate/`
- Can be reached via `/practice/:topic` (URL param) or with `location.state.topic` (from CompactTutor "Practice Now" button)
- If a topic is detected on mount (from URL param or route state), auto-generates a question immediately

#### `Dashboard.tsx`
- Stat cards use colored icon background pills with gradient tint
- Weekly activity shown as a list (`DailyStudyStats`)
- Empty state when no enrollments → "Browse Courses" CTA
- Achievements pulled from `getMyAchievements()`

#### `Profile.tsx`
- Stats (Days Active, Achievements, Messages) pulled from `StudentProfile` + `UserAchievement[]`
- Weekly activity bar chart uses `getDailyStats()` aligned to Mon–Sun of current week
- Preferences toggles (Email, Voice, Reminders) auto-save via `PATCH /users/preferences/`
- Achievements grid shows real earned achievements from API

---

### Design System (Tailwind conventions)

| Element | Class pattern |
|---------|--------------|
| Primary gradient button | `bg-gradient-to-r from-primary to-secondary text-white rounded-xl` |
| Secondary gradient button | `bg-gradient-to-r from-secondary to-accent text-white rounded-xl` |
| Card | `bg-card rounded-2xl border border-border shadow-sm` |
| Section heading | `text-lg font-semibold` |
| Muted label | `text-sm text-muted-foreground` |
| Difficulty badge | `difficultyColor()` helper → emerald/amber/rose |
| Loading spinner | `<Loader2 size={40} className="animate-spin text-secondary" />` |
| Error/success notifications | Sonner toast (`toast.error()`, `toast.success()`) — never `alert()` |
| Empty state | centered lucide icon in muted rounded box + heading + CTA |

**Sonner `<Toaster />` is mounted in `App.tsx`** — always use `toast` from `sonner`, not `alert()`.

---

## User Flow (End-to-End)

```
/login → authenticate → /dashboard

/courses → browse catalog → click card → /courses/:courseId
                                          ↓
                              [unenrolled] "Start Assessment & Enroll"
                                          ↓
                              POST /courses/enrollments/
                                          ↓
                              /courses/:courseId/assessment
                                          ↓
                              6 MCQ questions (AI or static fallback)
                                          ↓
                              PATCH enrollment.placement_score
                                          ↓
                              Results screen → "Begin Learning" → /dashboard

[enrolled] click "Continue Learning" → /course/:courseId/lesson/:lessonId
                                          ↓
                              Slides Viewer + AI Tutor (Dr. Nova)
                              ├── Real-time emotion tracking (FER + SER → fusedEmotion)
                              ├── Adaptive voice prosody (rate/pitch change)
                              ├── NovaAvatar animated expressions
                              ├── Fullscreen mode with floating tutor overlay
                              Prev/Next navigates between slides AND lessons
                              "Complete & Next" marks complete → next lesson
                                          ↓
                              Last lesson → "Finish Course" → /dashboard
                                          ↓
                              Session end → profiler LLM → overwrite StudentLearningProfile
```

---

## Known Issues / Implementation Notes

- `total_lessons_count` on the `Course` model is a stored field (default 0) that never auto-updates. **The serializer overrides it** with a computed `SerializerMethodField`. Never set it manually.
- `GET /api/assessments/generate` does **not exist** in the AI service yet — `Assessment.tsx` falls back to a hardcoded static question bank. Implement in `ai_service/routers/` if AI-generated questions are needed.
- `Enrollment.current_pathway` (JSON) is designed to hold the AI-personalized lesson pathway — not yet wired to any UI.
- `AIChatLog` model exists in the backend but no frontend UI reads/writes it yet.
- The `LiveSession` route pattern is `/course/:courseId/lesson/:lessonId` (no `s` on course). The `CourseDetail` route is `/courses/:courseId` (with `s`). Keep these consistent.
- Tutor sessions are stored **in-memory** in `tutor_service.py` — they are lost on AI service restart. No persistence to DB.
- The AI service requires `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_API_KEY` env vars for Dr. Nova to work. Without them the tutor endpoints will fail.
- `edge-tts` (Microsoft Neural Voice) requires no API key. Default voice: `en-US-AndrewMultilingualNeural`.
- **Session data is ephemeral** — emotion events are cached in-memory only (`emotionLogger.ts`). At session end the log is passed to the profiler LLM and then cleared. Nothing about individual interactions ever touches the database.
- **Pre-existing TypeScript errors** in `src/components/ui/` (accordion, switch, alert-dialog) are due to missing `@radix-ui` type packages. These are unrelated to the tutor/avatar code.
- The CSS lint warnings about `@custom-variant`, `@theme`, `@apply` in `globals.css` are standard Tailwind v4 directives and can be ignored.

---

## Seeding Test Data

Run via Django shell or a script:
```python
from apps.courses.models import Course, Module, Lesson
import json

course = Course.objects.create(
    title='Python for Beginners',
    description='...',
    difficulty='Beginner',
    price='0.00',
    tags=['python'],
    status='Published',
    is_published=True,
    syllabus=json.dumps(['Learn variables', 'Understand loops', ...]),
)
module = Module.objects.create(course=course, title='Getting Started', module_order=1)
Lesson.objects.create(module=module, title='Introduction', lesson_order=1)
```

Currently seeded courses (IDs 3–7):
- [3] Python for Beginners — Beginner — Free
- [4] Data Structures & Algorithms — Intermediate — Free
- [5] Web Development with Django — Intermediate — $29.99
- [6] Machine Learning Fundamentals — Advanced — $49.99
- [7] JavaScript & React — Beginner — Free

---

## Tech Stack Summary

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend framework | React | 18.3.1 |
| Frontend build | Vite | 6.3.5 |
| Frontend routing | React Router | 7.13.1 |
| Frontend HTTP | Axios | 1.13.5 |
| Frontend UI | Tailwind CSS + Radix UI (shadcn/ui) | — |
| Frontend charts | Recharts | 2.15.2 |
| Frontend code editor | Monaco Editor | 4.7.0 |
| Frontend icons | Lucide React | 0.487.0 |
| Frontend toasts | Sonner | 2.0.3 |
| Frontend avatar | Canvas2D + Spring Physics (NovaAvatar.tsx) | — |
| Backend framework | Django + DRF | 4.2 |
| Backend auth | Token Authentication | — |
| Database | Supabase (PostgreSQL) | 15 |
| AI service | FastAPI + Uvicorn | 0.104+ |
| LLM (coding) | Groq (llama-3.1-8b-instant) | — |
| LLM (tutor) | Ollama Cloud (configurable model) | — |
| LLM (profiler) | Groq (llama-3.1-8b-instant) | — |
| LLM (emotion fusion) | Groq (llama-3.1-8b-instant) | — |
| Code generation | Custom T5 (LeetCode fine-tuned) | — |
| ASR | OpenAI Whisper | tiny model |
| TTS | edge-tts (en-US-AndrewMultilingualNeural) | 6.1+ |
| FER | Custom model (facial emotion recognition) | — |
| SER | Custom model (speech emotion recognition) | — |
| Caching (planned) | Redis | 7 |
