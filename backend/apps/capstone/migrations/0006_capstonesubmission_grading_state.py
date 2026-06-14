from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("capstone", "0005_team_role_advice_team_role_advice_generated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="capstonesubmission",
            name="grading_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="capstonesubmission",
            name="grading_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
