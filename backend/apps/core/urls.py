"""Core app URLs — health check & AI proxy."""

from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health_check, name="health-check")
]
