from django.urls import path
from . import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="user-register"),
    path("me/", views.me, name="user-me"),
]
