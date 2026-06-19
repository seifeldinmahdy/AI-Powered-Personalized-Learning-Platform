from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("progress", "0016_remove_aichatlog_lesson_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="studentlearningprofile",
            name="profile_summary_source",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
