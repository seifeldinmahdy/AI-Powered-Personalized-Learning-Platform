from django.contrib import admin
from .models import SurveyTemplate, SurveyQuestion, SurveyResponse, SurveySummary

admin.site.register(SurveyTemplate)
admin.site.register(SurveyQuestion)
admin.site.register(SurveyResponse)
admin.site.register(SurveySummary)
