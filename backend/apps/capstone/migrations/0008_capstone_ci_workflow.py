from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("capstone", "0007_capstone_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="capstone",
            name="ci_workflow",
            field=models.TextField(blank=True, default=""),
        ),
    ]
