"""
FastAPI AI Service — entry point.
"""

import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import health, asr, coding
from routers import intent, tts, fer, ser, tutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

load_dotenv()

app = FastAPI(
    title="AI Learning Platform"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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