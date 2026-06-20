"""
Django settings for AI-Powered Personalized Learning Platform.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------- Startup guard (A.6) ----------
# Fail fast if critical secrets are missing.  Disabled during tests.
_REQUIRED_ENV_VARS = ["DJANGO_SECRET_KEY", "DB_PASSWORD", "INTERNAL_SERVICE_KEY"]
_MISSING = [k for k in _REQUIRED_ENV_VARS if not os.getenv(k)]
if _MISSING and not os.getenv("DJANGO_TESTING"):
    print(
        f"WARNING: Missing recommended env vars: {', '.join(_MISSING)}.  "
        "Set DJANGO_TESTING=1 to suppress this check.",
        file=sys.stderr,
    )

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me-in-production")

DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ---------- Application definition ----------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "axes",
    # Local apps
    "apps.core",
    "apps.users",
    "apps.courses",
    "apps.progress",
    "apps.gamification",
    "apps.feedback",
    "apps.capstone",
    "apps.artifacts",
    "apps.ai_proxy",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------- Database (PostgreSQL) ----------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "postgres"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT", "5432"),
        # Reuse a connection across requests instead of opening a fresh one each
        # time — this skips the TLS handshake + Supabase pooler auth round-trip
        # per request, which is the bulk of the per-call latency to a remote DB.
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        # Validate a reused connection at the start of each request; if Supabase's
        # pooler dropped it (the "server closed the connection unexpectedly" 500),
        # Django reconnects transparently instead of erroring. Needs Django 4.1+.
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "sslmode": os.getenv("DB_SSLMODE", "require"),
            # Detect a dropped pooler socket fast instead of hanging: give up
            # connecting after 10s, and let TCP keepalives tear down a half-open
            # connection (probe after 30s idle, every 10s, dead after 5 misses).
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
    }
}

# ---------- Cache (Redis/LocMem) ----------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# ---------- Auth ----------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "users.User"

# ---------- i18n ----------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------- Static ----------
STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- REST Framework ----------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "apps.core.authentication.InternalServiceAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/minute",
        "user": "120/minute",
        "admin_write": "10/minute",
        "feedback": "30/hour",
        "anon_feedback": "0/minute",
    },
}

# ---------- SimpleJWT ----------
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "UPDATE_LAST_LOGIN": True,
}

# ---------- CORS ----------
CORS_ALLOWED_ORIGINS = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
).split(",")
CORS_ALLOW_CREDENTIALS = True

# ---------- FastAPI AI Service ----------
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")

# ---------- Mastery tiers + remediation (Batch 6 / 11a) ----------
# Concept mastery scores are 0.0–1.0. These tiers anchor the platform's reads
# (derive_mastery_level uses the same intermediate/expert cut points).
MASTERY_INTERMEDIATE_THRESHOLD = float(os.getenv("MASTERY_INTERMEDIATE_THRESHOLD", "0.45"))
MASTERY_EXPERT_THRESHOLD = float(os.getenv("MASTERY_EXPERT_THRESHOLD", "0.75"))
# Remediation trigger/resolve, anchored to the tiers and individually tunable.
# A concept dropping BELOW the trigger floor inserts one review step; the step
# auto-resolves ONLY when the score recovers to the resolve bar (hysteresis above
# the floor prevents flapping). The review action itself never resolves it.
REMEDIATION_TRIGGER_THRESHOLD = float(
    os.getenv("REMEDIATION_TRIGGER_THRESHOLD", str(MASTERY_INTERMEDIATE_THRESHOLD))
)
REMEDIATION_RESOLVE_THRESHOLD = float(os.getenv("REMEDIATION_RESOLVE_THRESHOLD", "0.55"))

# ---------- Emotion governance (Batch 11b) ----------
# Emotion (FER/SER) is a low-confidence, OPTIONAL auxiliary signal. Capture is
# OFF by default and requires explicit opt-in consent before any webcam access.
# Nothing required for learning/grading/mastery/completion depends on it.
EMOTION_CONSENT_REQUIRED = os.getenv("EMOTION_CONSENT_REQUIRED", "True").lower() in ("true", "1", "yes")
EMOTION_CONSENT_POLICY_VERSION = os.getenv("EMOTION_CONSENT_POLICY_VERSION", "2026-06-15")
# Raw per-event emotion signals are short-lived: purged after the session
# profiler consolidates them (and a TTL backstop for abandoned sessions). Only
# the derived, qualitative low-confidence profile claim persists.
EMOTION_RAW_RETENTION_TTL = int(os.getenv("EMOTION_RAW_RETENTION_TTL", str(24 * 3600)))

# ---------- GitHub App (capstone provisioning) ----------
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "")
GITHUB_APP_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY", "")  # PEM content
GITHUB_APP_INSTALLATION_ID = os.getenv("GITHUB_APP_INSTALLATION_ID", "")
GITHUB_ORG = os.getenv("GITHUB_ORG", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

# Intent classifier retraining paths
# Absolute path to the Intent_Classifier_Model directory on the host running
# the Django backend (used by check_intent_retraining to export feedback CSV).
INTENT_CLASSIFIER_MODEL_DIR = os.getenv(
    "INTENT_CLASSIFIER_MODEL_DIR",
    str(BASE_DIR.parent / "Intent_Classifier_Model"),
)

# Shared secret for service-to-service calls from Django to the AI service.
# Must match the AI service's INTERNAL_SERVICE_KEY env var.
AI_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

# ---------- Security Headers (A.8) ----------
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True

# Production-only TLS settings (A.11) — enable when deploying behind HTTPS.
# SECURE_SSL_REDIRECT = os.getenv("IS_PRODUCTION", "").lower() in ("true", "1")
# SECURE_HSTS_SECONDS = 300  # start low; increase to 31536000 after testing
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = False

# ---------- django-axes (A.5) — brute-force login lockout ----------
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25  # hours (= 15 minutes)
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_CALLABLE = "apps.core.lockout.axes_lockout_handler"

