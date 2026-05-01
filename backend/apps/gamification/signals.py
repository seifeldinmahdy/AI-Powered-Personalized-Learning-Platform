from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import date, timedelta

from apps.progress.models import LessonCompletion
from apps.users.models import StudentProfile
from .models import Achievement, UserAchievement, DailyStudyStats, Notification


# XP rewards
XP_LESSON_COMPLETE = 50
XP_FIRST_LESSON = 100
XP_COURSE_COMPLETE = 200

# Level thresholds: level = floor(xp / 200) + 1, capped at 10
def xp_to_level(xp):
    return min(10, xp // 200 + 1)


def award_achievement(user, name):
    """Award an achievement to a user if they don't already have it. Returns True if newly awarded."""
    try:
        achievement = Achievement.objects.get(name=name)
    except Achievement.DoesNotExist:
        return False
    _, created = UserAchievement.objects.get_or_create(user=user, achievement=achievement)
    if created:
        Notification.objects.create(
            user=user,
            type="achievement",
            title=f"Achievement Unlocked: {achievement.name}",
            body=achievement.description,
        )
    return created


def update_streak(profile):
    """Recalculate current streak based on DailyStudyStats."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    studied_today = DailyStudyStats.objects.filter(user=profile.user, study_date=today).exists()
    studied_yesterday = DailyStudyStats.objects.filter(user=profile.user, study_date=yesterday).exists()

    if studied_today:
        if studied_yesterday or profile.current_streak == 0:
            profile.current_streak += 1
        # else streak already counted for today
    else:
        profile.current_streak = 0

    if profile.current_streak > profile.longest_streak:
        profile.longest_streak = profile.current_streak


@receiver(post_save, sender=LessonCompletion)
def on_lesson_completion(sender, instance, **kwargs):
    if instance.status != "Completed" or not instance.completed_at:
        return

    user = instance.enrollment.student
    try:
        profile = user.student_profile
    except StudentProfile.DoesNotExist:
        return

    # --- XP ---
    completed_count = LessonCompletion.objects.filter(
        enrollment__student=user, status="Completed"
    ).count()

    xp_gained = XP_LESSON_COMPLETE
    if completed_count == 1:
        xp_gained += XP_FIRST_LESSON  # bonus for very first lesson

    profile.current_xp += xp_gained
    profile.level = xp_to_level(profile.current_xp)
    raw_minutes = getattr(instance, "time_spent_minutes", 30) or 30
    profile.total_minutes_learned += min(raw_minutes, 240)  # cap at 4h

    # --- Study time log ---
    today = date.today()
    stats, _ = DailyStudyStats.objects.get_or_create(
        user=user, study_date=today,
        defaults={"hours_spent": 0}
    )
    raw_minutes = getattr(instance, "time_spent_minutes", 30) or 30
    hours_this_lesson = min(raw_minutes / 60.0, 4.0)  # cap at 4h
    stats.hours_spent = float(stats.hours_spent) + hours_this_lesson
    stats.save()

    # --- Streak ---
    update_streak(profile)

    # --- Days active ---
    profile.days_active = DailyStudyStats.objects.filter(user=user).count()

    profile.save()

    # --- Achievements ---
    newly_earned = []

    # First lesson
    if completed_count == 1:
        if award_achievement(user, "First Step"):
            newly_earned.append("First Step")

    # Lesson milestones
    milestones = {5: "Getting Started", 10: "On a Roll", 25: "Dedicated Learner", 50: "Knowledge Seeker", 100: "Master Student"}
    for threshold, name in milestones.items():
        if completed_count == threshold:
            if award_achievement(user, name):
                newly_earned.append(name)

    # XP milestones
    xp_milestones = {500: "XP Hunter", 1000: "XP Master", 5000: "XP Legend"}
    for threshold, name in xp_milestones.items():
        if profile.current_xp >= threshold:
            if award_achievement(user, name):
                newly_earned.append(name)

    # Streak milestones
    streak_milestones = {3: "Hat Trick", 7: "Week Warrior", 30: "Monthly Champion"}
    for threshold, name in streak_milestones.items():
        if profile.current_streak == threshold:
            if award_achievement(user, name):
                newly_earned.append(name)

    # Level milestones
    level_milestones = {5: "Halfway There", 10: "Max Level"}
    for threshold, name in level_milestones.items():
        if profile.level == threshold:
            if award_achievement(user, name):
                newly_earned.append(name)

    # Course completion bonus
    from apps.courses.models import Enrollment
    enrollment = instance.enrollment
    total_lessons = enrollment.course.total_lessons_count
    if total_lessons > 0:
        completed_in_course = LessonCompletion.objects.filter(
            enrollment=enrollment, status="Completed"
        ).count()
        if completed_in_course >= total_lessons:
            # Award +200 XP bonus (once per course via a one-time enrollment flag check)
            Enrollment.objects.filter(pk=enrollment.pk).update(progress_percentage=100.0)
            profile.current_xp += XP_COURSE_COMPLETE
            profile.level = xp_to_level(profile.current_xp)
            profile.save()

            # Count completed courses for this student
            completed_courses = Enrollment.objects.filter(
                student=user, progress_percentage=100.0
            ).count()
            course_milestones = {1: "Course Graduate", 2: "Double Major", 5: "Overachiever"}
            for threshold, name in course_milestones.items():
                if completed_courses == threshold:
                    if award_achievement(user, name):
                        newly_earned.append(name)
