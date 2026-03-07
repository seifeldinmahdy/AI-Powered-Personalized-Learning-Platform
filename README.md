# AI-Powered Personalized Learning Platform

| Layer | Tech | Port | Directory |
|-------|------|------|-----------|
| **Frontend** | React 18 | `3000` | `frontend/` |
| **Backend API** | Django 4.2 + DRF | `8000` | `backend/` |
| **AI Service** | FastAPI + scikit-learn | `8001` | `ai_service/` |
| **Database** | Supabase (PostgreSQL) | `6543` | — |

## Architecture

```
React (3000)  ──►  Django REST (8000)  ──►  FastAPI AI (8001)
                         │
                  Supabase PostgreSQL
```

## Setup

**1. Backend (Django)**
```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

**2. AI Service (FastAPI)**
```bash
cd ai_service
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

**3. Frontend (React)**
```bash
cd frontend
npm install
npm start
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your Supabase credentials.
You can find them in **Supabase Dashboard → Project Settings → Database**.

| Variable | Description |
|----------|-------------|
| `DB_USER` | `postgres.YOUR_PROJECT_REF` |
| `DB_PASSWORD` | Your Supabase database password |
| `DB_HOST` | `aws-0-REGION.pooler.supabase.com` |
| `DB_PORT` | `6543` (connection pooler) |
| `AI_SERVICE_URL` | FastAPI service URL |
| `REACT_APP_API_URL` | Django API URL for React |
