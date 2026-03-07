"""
FastAPI AI Service — entry point.
"""

import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import health, asr
from routers import coding

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
        "service": "AI Learning Platform - ASR API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "asr_transcribe": "/asr/transcribe",
            "asr_health": "/asr/health",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }

# Include routers
app.include_router(health.router)
app.include_router(asr.router)


app.include_router(coding.router)