from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("progress", "0011_profile_data_to_claims_v2"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessoncompletion",
            name="gamification_awarded",
            field=models.BooleanField(default=False),
        ),
    ]
