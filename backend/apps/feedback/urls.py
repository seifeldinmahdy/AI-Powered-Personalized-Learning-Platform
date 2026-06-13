from django.urls import path
from . import views

urlpatterns = [
    path("surveys/status/", views.survey_status, name="survey-status"),
    path("surveys/respond/", views.survey_respond, name="survey-respond"),
    path("surveys/<int:course_id>/questions/", views.survey_questions, name="survey-questions"),
    path("surveys/<int:course_id>/summary/", views.survey_summary_view, name="survey-summary"),
    path("surveys/<int:course_id>/refresh/", views.survey_refresh, name="survey-refresh"),
]
