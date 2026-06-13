import uuid

import django.db.models.deletion
from django.db import migrations, models

import apps.courses.models


def create_corpus_per_course(apps, schema_editor):
    """Backfill: create exactly one corpus for every existing course.

    Relational backfill only — this does NOT touch ChromaDB. Stamping existing
    vectors with their corpus_id is a separate, idempotent operational step:
    the ``backfill_corpus_vector_tags`` management command.
    """
    Course = apps.get_model("courses", "Course")
    CourseCorpus = apps.get_model("courses", "CourseCorpus")
    for course in Course.objects.all():
        CourseCorpus.objects.get_or_create(
            course=course,
            defaults={"corpus_id": uuid.uuid4().hex, "name": course.title},
        )


def remove_all_corpora(apps, schema_editor):
    CourseCorpus = apps.get_model("courses", "CourseCorpus")
    CourseCorpus.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0007_enrollment_completed_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="CourseCorpus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("corpus_id", models.CharField(default=apps.courses.models._new_corpus_id, editable=False, help_text="Stable, opaque retrieval scope key. Never changes.", max_length=64, unique=True)),
                ("name", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("course", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="corpus", to="courses.course")),
            ],
            options={
                "verbose_name": "Course Corpus",
                "verbose_name_plural": "Course Corpora",
                "db_table": "course_corpora",
            },
        ),
        migrations.CreateModel(
            name="CorpusSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=300)),
                ("book_stem", models.CharField(help_text="Ingestion key; must match the ChromaDB 'book' value for this source.", max_length=200)),
                ("source_type", models.CharField(choices=[("pdf", "PDF"), ("doc", "Document"), ("url", "URL")], default="pdf", max_length=10)),
                ("is_active", models.BooleanField(default=True)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("concept", models.ForeignKey(blank=True, help_text="Optional concept binding. Batch 4 makes concept tagging non-optional.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="corpus_sources", to="courses.concept")),
                ("corpus", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sources", to="courses.coursecorpus")),
            ],
            options={
                "verbose_name": "Corpus Source",
                "verbose_name_plural": "Corpus Sources",
                "db_table": "corpus_sources",
                "ordering": ["added_at"],
                "unique_together": {("corpus", "book_stem")},
            },
        ),
        migrations.RunPython(create_corpus_per_course, remove_all_corpora),
    ]
