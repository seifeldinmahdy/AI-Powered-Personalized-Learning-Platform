"""
FastAPI AI Service — entry point.
"""

import os
import sys
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Add intent_model to path before any routers are imported
_intent_model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intent_model")
if _intent_model_dir not in sys.path:
    sys.path.insert(0, _intent_model_dir)
from fastapi.middleware.cors import CORSMiddleware
from routers import health, asr, coding, assessments, student_context
from routers import intent, tts, fer, ser, tutor, rag, profiler, slides, session
from routers import a2f_health, problem_set, clos, surveys, capstone as capstone_router
from routers import pathway_admin, remediation, emotion, corpus, authoring

# Add course_pathway to sys.path for the pathway router
from pathlib import Path as _Path
_pathway_dir = str(_Path(__file__).resolve().parent.parent / "course_pathway")
if _pathway_dir not in sys.path:
    sys.path.insert(0, _pathway_dir)
from router import router as pathway_router  # type: ignore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

load_dotenv()

app = FastAPI(
    title="AI Learning Platform"
)

# CORS middleware — restrict to known origins (addresses security liability L2).
# Set CORS_ORIGINS in .env as a comma-separated list.  Defaults to local dev.
_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    return {
        "service": "AI Learning Platform — AI Services API",
        "version": "1.2.0",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "asr_transcribe": "/asr/transcribe",
            "asr_health": "/asr/health",
            "coding_generate": "/api/coding/generate",
            "coding_evaluate": "/api/coding/evaluate",
            "intent_classify": "/intent/classify",
            "intent_health": "/intent/health",
            "tts_synthesize": "/tts/synthesize",
            "tts_voices": "/tts/voices",
            "tts_health": "/tts/health",
            "fer_predict": "/fer/predict",
            "fer_predict_video": "/fer/predict-video",
            "fer_health": "/fer/health",
            "ser_predict": "/ser/predict",
            "ser_predict_stream": "/ser/predict-stream",
            "ser_health": "/ser/health",
            "tutor_start": "/tutor/start",
            "tutor_continue": "/tutor/continue",
            "tutor_ask": "/tutor/ask",
            "tutor_status": "/tutor/status",
            "tutor_health": "/tutor/health",
            "profiler_update": "/profiler/update",
            "profiler_fuse_emotions": "/profiler/fuse-emotions",
            "pathway_generate": "/pathway/generate",
            "pathway_health": "/pathway/health",
            "slides_generate": "/slides/generate",
            "slides_health": "/slides/health",
            "session_delete": "/session/{session_id} [DELETE]",
            "session_get": "/session/{session_id} [GET]",
            "assessments_generate": "/assessments/generate",
            "assessments_submit": "/assessments/submit-placement",
            "assessments_health": "/assessments/health",
            "a2f_health": "/a2f/health",
            "student_context_get": "/student-context/{student_id}/{course_id}",
            "problem_set_generate": "/problem-set/generate",
            "problem_set_submit": "/problem-set/submit",
            "problem_set_get": "/problem-set/{problem_set_id}",
            "student_context_update_performance": "/student-context/{student_id}/{course_id}/update-performance",
        }
    }

# Include routers
app.include_router(health.router)
app.include_router(asr.router)
app.include_router(coding.router)
app.include_router(intent.router)
app.include_router(tts.router)
app.include_router(fer.router)
app.include_router(ser.router)
app.include_router(tutor.router)
app.include_router(rag.router)
app.include_router(profiler.router)
app.include_router(slides.router)
app.include_router(session.router)
app.include_router(assessments.router)
app.include_router(pathway_router)
app.include_router(pathway_admin.router)
app.include_router(a2f_health.router)
app.include_router(student_context.router)
app.include_router(problem_set.router)
app.include_router(clos.router)
app.include_router(surveys.router)
app.include_router(capstone_router.router)
app.include_router(remediation.router)
app.include_router(emotion.router)
app.include_router(corpus.router)
app.include_router(authoring.router)

# Serve static files (3D avatar model, etc.)
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
