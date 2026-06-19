from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("capstone", "0006_capstonesubmission_grading_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="capstone",
            name="language",
            field=models.CharField(
                default="python",
                max_length=30,
                help_text="e.g. python, javascript, typescript, java, go, cpp, ruby, php.",
            ),
        ),
    ]
