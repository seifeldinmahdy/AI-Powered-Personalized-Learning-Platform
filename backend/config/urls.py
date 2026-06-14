"""Root URL configuration."""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/users/", include("apps.users.urls")),
    path("api/courses/", include("apps.courses.urls")),
    path("api/progress/", include("apps.progress.urls")),
    path("api/gamification/", include("apps.gamification.urls")),
    path("api/feedback/", include("apps.feedback.urls")),
    path("api/capstone/", include("apps.capstone.urls")),
    path("api/artifacts/", include("apps.artifacts.urls")),
]
