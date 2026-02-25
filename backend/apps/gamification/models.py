from django.db import models
from django.conf import settings


# ------------------------------------------------------------------
# Achievement — platform-wide achievement definitions
# ------------------------------------------------------------------
class Achievement(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    xp_reward = models.IntegerField(default=0)
    icon_url = models.TextField(blank=True, default="")

    class Meta:
        db_table = "achievements"
        verbose_name = "Achievement"
        verbose_name_plural = "Achievements"

    def __str__(self):
        return f"{self.name} (+{self.xp_reward} XP)"


# ------------------------------------------------------------------
# User Achievement — junction table: which user earned which badge
# ------------------------------------------------------------------
class UserAchievement(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="earned_achievements",
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name="user_achievements",
    )
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_achievements"
        unique_together = ["user", "achievement"]
        verbose_name = "User Achievement"
        verbose_name_plural = "User Achievements"

    def __str__(self):
        return f"{self.user.username} earned {self.achievement.name}"


# ------------------------------------------------------------------
# Daily Study Stats — per-user, per-day study hours
# ------------------------------------------------------------------
class DailyStudyStats(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_study_stats",
    )
    study_date = models.DateField()
    hours_spent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    class Meta:
        db_table = "daily_study_stats"
        unique_together = ["user", "study_date"]
        verbose_name = "Daily Study Stats"
        verbose_name_plural = "Daily Study Stats"

    def __str__(self):
        return f"{self.user.username} — {self.study_date} ({self.hours_spent}h)"
