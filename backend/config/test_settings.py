"""Test settings that use SQLite so migrations/commands can be verified locally."""
from .settings import *  # noqa: F401,F403

ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_test.sqlite3",  # noqa: F405
    }
}
