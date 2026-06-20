<div align="center">

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img alt="PersonifAI." src="assets/logo-light.svg" width="460">
  </picture>
</p>

### AI-Powered Personalized Learning Platform

**An adaptive computer-science tutor that turns your own textbooks into a personalized course — taught live, one student at a time.**

A placement test profiles each learner; the platform then generates a per-student **learning pathway**, teaches it through a **live AI tutor** with personalized slides, and continuously adapts coding problem sets, MCQs, remediation, and a capstone to the learner's evolving mastery — all grounded in the course's own corpus.

<br>

![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![Django](https://img.shields.io/badge/Django-DRF-092E20?logo=django&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Uvicorn-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-pgvector-3FCF8E?logo=supabase&logoColor=white)

</div>

---

## 📑 Table of Contents

- [Highlights](#-highlights)
- [Architecture](#-architecture)
- [Components](#-components)
- [AI / ML Models](#-ai--ml-models)
- [Repository Layout](#-repository-layout)
- [Prerequisites](#-prerequisites)
- [Setup](#-setup)
- [Environment Variables](#-environment-variables)
- [How It Works](#-how-it-works)
- [Feature Catalog](#-feature-catalog)
- [Engineering Notes](#-engineering-notes)

---

## ✨ Highlights

- 🧭 **Personalized pathways** — every student gets an ordered, mastery-scoped sequence of sessions generated from the course's corpus and learning outcomes. CLO coverage is guaranteed: each objective is grounded in real corpus chunks.
- 🤖 **Live AI tutor** — a Socratic, avatar-driven session with personalized, auto-generated slide decks, persistent per-session chat, and multimodal signals (intent, facial & speech emotion, voice).
- 📚 **Bring-your-own-textbook corpus** — admins upload PDFs that are indexed once and reused across many courses; concepts are auto-extracted and grounded back onto the content.
- 🎯 **Backward-designed assessments** — coding problem sets, MCQs, and rubric-based evaluation with adaptive hints; results drive a concept-level mastery signal.
- 🧪 **Placement & remediation** — adaptive placement seeds the learner profile; weak concepts trigger targeted remediation.
- 🏆 **Capstone & gamification** — an end-of-course project plus achievements, study streaks, notifications, and collaborative teams.
- 🔌 **Pluggable vector store** — local ChromaDB for development, Supabase `pgvector` for shared deployment — swapped transparently by env.

---

## 🏗 Architecture

```
                         ┌───────────────────────────────┐
   Browser               │      React 18 + Vite (5173)    │
                         └───────────────┬───────────────┘
                                         │  JWT (axios)
                                         ▼
                         ┌───────────────────────────────┐
   Authentication        │   Django REST Framework (8000) │   ← issues & verifies JWT
   boundary              │   ORM · proxy · authoring      │
                         └───────┬───────────────┬────────┘
              X-Service-Key +    │               │  Django ORM
              X-Student-ID       │               │
                                 ▼               ▼
            ┌────────────────────────────┐   ┌───────────────────────────┐
   AI tier  │      FastAPI AI service     │   │    Supabase PostgreSQL    │
            │           (8001)            │──►│   (session pooler · 5432) │
            │  tutor · slides · RAG       │   │   relational + pgvector   │
            │  pathway · problem sets     │   └───────────────────────────┘
            │  capstone · MCQ · emotion   │
            └─────────────┬──────────────┘
                          │ mounts
        ┌─────────────────┼──────────────────┬────────────────────┐
        ▼                 ▼                  ▼                    ▼
  course_pathway     rag_pipeline      slides-generator       mcq_service
  (plan gen)        (index/retrieve)   (T5 + classifier)      (QG + DG)
```

**Trust model.** The browser never talks to the AI service directly. **Django is the authentication boundary** — it verifies the user's JWT, then calls FastAPI with a shared `X-Service-Key` and an `X-Student-ID` header carrying the *verified* identity. The AI service trusts that header and never accepts a client-supplied student id.

---

## 🧩 Components

| Layer | Tech | Port | Directory |
|-------|------|:----:|-----------|
| **Frontend** | React 18 · Vite · TypeScript · React Router 7 · axios | `5173` | `frontend/` |
| **Backend API** | Django · Django REST Framework · SimpleJWT | `8000` | `backend/` |
| **AI Service** | FastAPI · Uvicorn | `8001` | `ai_service/` |
| **Pathway Generator** | Curriculum → sessions → personalization | _(mounted)_ | `course_pathway/` |
| **RAG Pipeline** | PDF → chunk → analyze → embed → scoped retrieval | _(library)_ | `rag_pipeline/` |
| **Slides Generator** | T5 content specialist + visual classifier | _(library)_ | `slides-generator/` |
| **MCQ Service** | Fine-tuned question + distractor generators | _(library)_ | `mcq_service/` |
| **Intent Classifier** | TinyBERT intent model + feedback loop | _(library)_ | `Intent_Classifier_Model/` |
| **Database** | Supabase (PostgreSQL + `pgvector`) | `5432` | — |

### Django apps (`backend/apps/`)
| App | Responsibility |
|-----|----------------|
| `users` | Accounts, roles, JWT/OAuth, student profiles, preferences, emotion consent |
| `courses` | Courses, concepts, CLOs, corpus & sources, placement questions, ratings |
| `progress` | Live sessions, session completion, concept mastery, AI chat logs, remediation, intent feedback |
| `artifacts` | Persisted student artifacts (slides, problem sets, placement attempts) |
| `capstone` | Capstone projects, proposals, submissions, rubric, AI-assist quotas |
| `feedback` | Survey templates, questions, responses, summaries |
| `gamification` | Achievements, XP, daily study stats, notifications, bookmarks, teams & matchmaking |
| `ai_proxy` | Authenticated pass-through from Django to the FastAPI AI service |
| `core` | Shared permissions, audit logs, system activity |

### AI service routers (`ai_service/routers/`)
`tutor` · `slides` · `session` · `student_context` · `pathway` · `pathway_admin` · `rag` · `corpus` · `authoring` · `clos` · `problem_set` · `coding` · `assessments` · `capstone` · `surveys` · `remediation` · `profiler` · `intent` · `emotion` · `fer` · `ser` · `asr` · `tts` · `health`

---

## 🧠 AI / ML Models

| Model | Role | Tech |
|-------|------|------|
| **Content Specialist** | Generates personalized slide bullets from textbook chunks | Fine-tuned **T5** (`slides-generator/`) |
| **Visual Classifier** | Decides which slides get diagrams/visuals and which template | Classifier (`slides-generator/`) |
| **MCQ Question Generator (QG)** | Produces MCQ stems + correct answers | Fine-tuned **Qwen3-4B** GGUF via Ollama |
| **MCQ Distractor Generator (DG)** | Produces plausible wrong options | Fine-tuned **Qwen3-4B** GGUF via Ollama |
| **Intent Classifier** | Classifies student utterances during tutoring + retrains from feedback | **TinyBERT** (`Intent_Classifier_Model/`) |
| **Emotion / Voice** | Facial (FER) & speech (SER) emotion, speech-to-text (ASR), text-to-speech (TTS) | `ai_service/routers/{fer,ser,asr,tts}` |
| **Generation / Evaluation LLM** | Pathway reasoning, concept extraction, problem-set authoring & grading | Ollama-hosted (configurable model) |
| **Embeddings** | Chunk & query vectors for retrieval | `sentence-transformers/all-MiniLM-L6-v2` (384-d) |

---

## 📁 Repository Layout

```
frontend/                 React + Vite client (pages: admin · student · auth · shared)
backend/                  Django project
  └─ apps/                users · courses · progress · artifacts · capstone
                          feedback · gamification · ai_proxy · core
ai_service/               FastAPI service (routers/ · services/ · schemas/)
course_pathway/           Pathway generation library (mounted into ai_service)
rag_pipeline/             Indexing + retrieval (Chroma OR Supabase pgvector)
slides-generator/         Slide model pipeline (T5 + visual classifier)
mcq_service/              MCQ generation / distractor models
Intent_Classifier_Model/  TinyBERT intent classifier + training
docs/                     System map · personalization audit · vector-store notes
```

---

## ✅ Prerequisites

- **Python 3.11+** — separate virtualenvs for `backend/` and `ai_service/`
- **Node 18+**
- A **Supabase** project (enable the `pgvector` extension)
- *(Optional)* **Ollama** for LLM generation/evaluation and the MCQ GGUF models

---

## 🚀 Setup

### 1. Backend — Django · port 8000
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### 2. AI Service — FastAPI · port 8001
```bash
cd ai_service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### 3. Frontend — React + Vite · port 5173
```bash
cd frontend
npm install
npm run dev                      # production bundle: npm run build
```

> ℹ️ The frontend is a **Vite** app — use `npm run dev`, **not** `npm start`.

---

## 🔐 Environment Variables

Each service reads its own `.env`. Use the Supabase **session pooler (port 5432)** so persistent connections stay stable.

<details>
<summary><b>backend/.env</b> — Django</summary>

| Variable | Description |
|----------|-------------|
| `DB_HOST` | `aws-0-REGION.pooler.supabase.com` |
| `DB_PORT` | `5432` (session pooler) |
| `DB_USER` | `postgres.YOUR_PROJECT_REF` |
| `DB_PASSWORD` | Supabase database password |
| `DB_NAME` | `postgres` |
| `VECTOR_BACKEND` | `supabase` (use `pgvector`) or `chroma` (local) |
| `SUPABASE_DB_URL` | Pooled DSN, e.g. `postgresql://USER:PASS@HOST:5432/postgres?sslmode=require` |
| `AI_SERVICE_URL` | FastAPI base URL (e.g. `http://localhost:8001`) |
| `INTERNAL_SERVICE_KEY` | Shared secret for Django → AI-service calls |

</details>

<details>
<summary><b>ai_service/.env</b> — FastAPI</summary>

| Variable | Description |
|----------|-------------|
| `VECTOR_BACKEND` | `supabase` to use Supabase `pgvector` (else local Chroma) |
| `SUPABASE_DB_URL` | Same pooled DSN as Django (port `5432`) |
| `DJANGO_API_URL` | Django API base, e.g. `http://localhost:8000/api` |
| `INTERNAL_SERVICE_KEY` | Must match Django's value |
| `OLLAMA_HOST` / `OLLAMA_API_KEY` | LLM endpoint + key |
| `OLLAMA_GEN_MODEL` / `OLLAMA_EVAL_MODEL` | Model ids for generation / evaluation |

</details>

<details>
<summary><b>frontend/.env</b> — React/Vite</summary>

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Django API base for the client (default `http://localhost:8000/api`) |

</details>

---

## 🔄 How It Works

### Student journey
1. **Enroll & place** — the student enrolls and takes a placement test; the AI service scores it and stores a `UnifiedStudentContext` (mastery, composition mode, language proficiency).
2. **Pathway generation** — `course_pathway` turns the corpus + CLOs into an ordered set of sessions scoped to the student's mastery, guaranteeing every objective is grounded in real chunks.
3. **Live session** — the AI tutor teaches each session with personalized, auto-generated slides; chat persists per session and adapts to facial/speech emotion and detected intent.
4. **Practice & assess** — coding problem sets and MCQs are generated from the session, evaluated against a rubric with adaptive hints; outcomes move the concept-level mastery signal and can trigger remediation.
5. **Capstone & feedback** — an end-of-course project plus surveys close the loop; achievements, streaks, and notifications keep learners engaged.

### Admin authoring & the corpus model
Books are **indexed once** into the shared vector store, then **attached** to a course's corpus via a per-corpus membership flag (`corpus__<corpus_id> = "1"`) — no re-embedding. The same book can serve many courses; **detaching** flips the flag (vectors stay for other courses) and cascades cleanup of now-orphaned auto concepts. Concepts are **auto-extracted** from a book's topics, grounded onto chunks (`concept__<corpus_id>`), and linked to CLOs (≤ 5 concepts per outcome).

---

## 📦 Feature Catalog

**For students**
- Course catalog, enrollment, and a personalized dashboard
- Adaptive placement test
- Personalized learning pathway with versioned plans
- Live AI tutor sessions with generated slides and persistent chat
- Coding labs and rubric-evaluated problem sets with adaptive hints
- Auto-generated MCQ checkpoints
- Targeted remediation for weak concepts
- Capstone project workspace, proposals, and submissions
- Surveys & feedback
- Gamification: achievements, XP, study streaks, notifications, teams

**For admins**
- Course editor (metadata, AI-drafted descriptions)
- Corpus management — upload/index books, attach/detach across courses, delete from library
- Concept & CLO authoring (auto-extraction + AI suggestions)
- Placement-question authoring
- Capstone editor with rubric authoring
- Student management, creation, and detail views
- AI operations, content management, enrollments, health monitoring, settings

---

## 🛠 Engineering Notes

- **Dual vector backend.** `VECTOR_BACKEND=chroma` → local ChromaDB; `supabase`/`pgvector` → the `course_chunks` table in Postgres. Both expose the same interface and are selected transparently — fully reversible via env.
- **Corpus-scoped retrieval.** A single `RetrievalService` enforces a mandatory corpus scope so queries can never leak across courses.
- **Versioned pathways.** Plans live authoritatively in the AI service; the frontend reads the current version rather than pushing one.
- **Durable artifacts.** Generated decks and problem sets persist as `StudentArtifact`s keyed by student + course + plan version + session, so resume is consistent and never cross-tenant.
- **Connection resilience.** Services use the Supabase session pooler with bounded connect timeouts, TCP keepalives, and connection reuse + health checks to ride out pooler hiccups.

---

<div align="center">
<sub>Built as a graduation project — a full-stack, multi-model adaptive learning system.</sub>
</div>
