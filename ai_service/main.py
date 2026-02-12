"""
FastAPI AI Service — entry point.
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import health

load_dotenv()

app = FastAPI(
    title="AI Learning Platform")

