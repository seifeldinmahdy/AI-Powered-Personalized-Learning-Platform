from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Lesson, Course


def _update_course_lesson_count(lesson):
    course = lesson.module.course
    count = Lesson.objects.filter(module__course=course).count()
    Course.objects.filter(pk=course.pk).update(total_lessons_count=count)


@receiver(post_save, sender=Lesson)
def lesson_saved(sender, instance, **kwargs):
    _update_course_lesson_count(instance)


@receiver(post_delete, sender=Lesson)
def lesson_deleted(sender, instance, **kwargs):
    _update_course_lesson_count(instance)
