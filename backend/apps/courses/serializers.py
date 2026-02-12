from rest_framework import serializers
from .models import Course, Enrollment


class CourseSerializer(serializers.ModelSerializer):
    instructor_name = serializers.ReadOnlyField(source="instructor.username")

    class Meta:
        model = Course
        fields = [
            "id", "title", "description", "instructor", "instructor_name",
            "difficulty", "tags", "is_published", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class EnrollmentSerializer(serializers.ModelSerializer):
    course_title = serializers.ReadOnlyField(source="course.title")

    class Meta:
        model = Enrollment
        fields = ["id", "student", "course", "course_title", "progress", "enrolled_at"]
        read_only_fields = ["id", "enrolled_at"]
