"""Tests for the Course Corpus: auto-creation, API, and serializer exposure."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.courses.models import Course, CourseCorpus, CorpusSource
from apps.users.models import User


class CourseCorpusModelTests(TestCase):
    def test_corpus_auto_created_with_course(self):
        course = Course.objects.create(title="Intro to Python")
        # Signal should have created exactly one corpus with a stable id.
        corpus = CourseCorpus.objects.get(course=course)
        assert corpus.corpus_id
        assert len(corpus.corpus_id) == 32  # uuid4().hex

    def test_corpus_id_is_unique_per_course(self):
        c1 = Course.objects.create(title="A")
        c2 = Course.objects.create(title="B")
        assert c1.corpus.corpus_id != c2.corpus.corpus_id

    def test_source_book_stem_unique_within_corpus(self):
        course = Course.objects.create(title="C")
        corpus = course.corpus
        CorpusSource.objects.create(corpus=corpus, title="Book", book_stem="bookx")
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CorpusSource.objects.create(corpus=corpus, title="Dup", book_stem="bookx")


class CourseCorpusAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.course = Course.objects.create(title="DS101")
        self.admin = User.objects.create_user(
            username="admin1", email="a@x.com", password="pw", role="admin",
        )
        self.student = User.objects.create_user(
            username="stu1", email="s@x.com", password="pw", role="student",
        )

    def test_get_corpus_is_open_and_returns_corpus_id(self):
        url = f"/api/courses/courses/{self.course.pk}/corpus/"
        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.json()["corpus_id"] == self.course.corpus.corpus_id
        assert resp.json()["sources"] == []

    def test_course_detail_exposes_corpus_id(self):
        resp = self.client.get(f"/api/courses/courses/{self.course.pk}/")
        assert resp.status_code == 200
        assert resp.json()["corpus_id"] == self.course.corpus.corpus_id

    def test_admin_can_add_and_remove_source(self):
        self.client.force_authenticate(user=self.admin)
        add_url = f"/api/courses/courses/{self.course.pk}/corpus/sources/"
        resp = self.client.post(
            add_url, {"title": "Think Python", "book_stem": "thinkpython", "source_type": "pdf"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        source_id = resp.json()["id"]
        assert CorpusSource.objects.filter(pk=source_id).exists()

        del_url = f"/api/courses/courses/{self.course.pk}/corpus/sources/{source_id}/"
        resp = self.client.delete(del_url)
        assert resp.status_code == 204
        assert not CorpusSource.objects.filter(pk=source_id).exists()

    def test_student_cannot_add_source(self):
        self.client.force_authenticate(user=self.student)
        add_url = f"/api/courses/courses/{self.course.pk}/corpus/sources/"
        resp = self.client.post(
            add_url, {"title": "X", "book_stem": "x"}, format="json",
        )
        assert resp.status_code in (401, 403)
