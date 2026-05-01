from django.core.management.base import BaseCommand
from apps.gamification.models import Achievement

ACHIEVEMENTS = [
    # Lesson milestones
    {"name": "First Step",          "description": "Complete your first lesson.",             "xp_reward": 100, "icon_url": "🎯"},
    {"name": "Getting Started",     "description": "Complete 5 lessons.",                     "xp_reward": 150, "icon_url": "🚀"},
    {"name": "On a Roll",           "description": "Complete 10 lessons.",                    "xp_reward": 200, "icon_url": "🔥"},
    {"name": "Dedicated Learner",   "description": "Complete 25 lessons.",                    "xp_reward": 300, "icon_url": "📚"},
    {"name": "Knowledge Seeker",    "description": "Complete 50 lessons.",                    "xp_reward": 500, "icon_url": "🔍"},
    {"name": "Master Student",      "description": "Complete 100 lessons.",                   "xp_reward": 1000, "icon_url": "🎓"},
    # XP milestones
    {"name": "XP Hunter",           "description": "Earn 500 XP.",                            "xp_reward": 50,  "icon_url": "⚡"},
    {"name": "XP Master",           "description": "Earn 1000 XP.",                           "xp_reward": 100, "icon_url": "💎"},
    {"name": "XP Legend",           "description": "Earn 5000 XP.",                           "xp_reward": 500, "icon_url": "👑"},
    # Streak milestones
    {"name": "Hat Trick",           "description": "Maintain a 3-day learning streak.",       "xp_reward": 75,  "icon_url": "🎩"},
    {"name": "Week Warrior",        "description": "Maintain a 7-day learning streak.",       "xp_reward": 150, "icon_url": "⚔️"},
    {"name": "Monthly Champion",    "description": "Maintain a 30-day learning streak.",      "xp_reward": 500, "icon_url": "🏆"},
    # Level milestones
    {"name": "Halfway There",       "description": "Reach level 5.",                          "xp_reward": 200, "icon_url": "🌟"},
    {"name": "Max Level",           "description": "Reach the maximum level 10.",             "xp_reward": 1000, "icon_url": "💫"},
    # Course completion milestones
    {"name": "Course Graduate",     "description": "Complete your first full course.",        "xp_reward": 500,  "icon_url": "🎓"},
    {"name": "Double Major",        "description": "Complete 2 full courses.",                "xp_reward": 750,  "icon_url": "📜"},
    {"name": "Overachiever",        "description": "Complete 5 full courses.",                "xp_reward": 1500, "icon_url": "🏅"},
]


class Command(BaseCommand):
    help = "Seed the database with default achievements"

    def handle(self, *args, **kwargs):
        created = 0
        for data in ACHIEVEMENTS:
            _, was_created = Achievement.objects.get_or_create(
                name=data["name"],
                defaults=data,
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created} new achievements created, {len(ACHIEVEMENTS) - created} already existed."
        ))
