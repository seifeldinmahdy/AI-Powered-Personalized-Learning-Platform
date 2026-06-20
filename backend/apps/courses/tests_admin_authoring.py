"""Admin authoring backend: corpus (list/upload/index), course-description AI
draft, and plan-versions — proxy wiring, admin gating, and CorpusSource status."""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.users.models import User
from apps.courses.models import Course, CourseCorpus, CorpusSource

VIEWS_REQ = "apps.courses.views.requests"


def _resp(status_code=200, payload=None):
    m = mock.Mock()
    m.status_code = status_code
    m.json.return_value = payload or {}
    return m


class Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="adm", email="a@x.com", password="pw", role="admin")
        self.student = User.objects.create_user(username="stu", email="s@x.com", password="pw", role="student")
        self.course = Course.objects.create(title="Py", description="old")
        self.admin_c = APIClient(); self.admin_c.force_authenticate(self.admin)
        self.stu_c = APIClient(); self.stu_c.force_authenticate(self.student)


class CorpusAuthoringTests(Base):
    def test_available_books_admin_only(self):
        r = self.stu_c.get(f"/api/courses/courses/{self.course.id}/corpus/available-books/")
        self.assertEqual(r.status_code, 403)

    def test_available_books_proxies_ai(self):
        with mock.patch(VIEWS_REQ) as m:
            m.get.return_value = _resp(200, {"books": [{"book_stem": "intro", "file_present": True}]})
            r = self.admin_c.get(f"/api/courses/courses/{self.course.id}/corpus/available-books/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["books"][0]["book_stem"], "intro")
        self.assertIn("/corpus/available-books", m.get.call_args.args[0])

    def test_upload_book_forwards_file(self):
        pdf = SimpleUploadedFile("intro.pdf", b"%PDF-1.4 ...", content_type="application/pdf")
        with mock.patch(VIEWS_REQ) as m:
            m.post.return_value = _resp(200, {"book_stem": "intro"})
            r = self.admin_c.post(
                f"/api/courses/courses/{self.course.id}/corpus/upload/",
                {"file": pdf}, format="multipart",
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["book_stem"], "intro")
        self.assertIn("/corpus/upload", m.post.call_args.args[0])

    def test_add_source_triggers_autoindex_and_records_status(self):
        with mock.patch(VIEWS_REQ) as m:
            m.post.return_value = _resp(200, {"status": "indexing", "book_stem": "intro"})
            r = self.admin_c.post(
                f"/api/courses/courses/{self.course.id}/corpus/sources/",
                {"title": "Intro", "book_stem": "intro", "source_type": "pdf"}, format="json",
            )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["index_status"], "indexing")
        src = CorpusSource.objects.get(book_stem="intro")
        self.assertEqual(src.index_status, "indexing")
        # The AI corpus attach endpoint was called with this corpus + book + course.
        self.assertIn("/corpus/attach", m.post.call_args.args[0])
        self.assertEqual(m.post.call_args.kwargs["json"]["book_stem"], "intro")
        self.assertEqual(m.post.call_args.kwargs["json"]["course_id"], str(self.course.id))

    def test_index_status_syncs_onto_source(self):
        corpus = CourseCorpus.objects.get_or_create(course=self.course, defaults={"name": "Py"})[0]
        src = CorpusSource.objects.create(corpus=corpus, title="Intro", book_stem="intro", index_status="indexing")
        with mock.patch(VIEWS_REQ) as m:
            m.get.return_value = _resp(200, {"status": "indexed", "chunks": 42})
            r = self.admin_c.get(
                f"/api/courses/courses/{self.course.id}/corpus/index-status/?book_stem=intro")
        self.assertEqual(r.status_code, 200)
        src.refresh_from_db()
        self.assertEqual(src.index_status, "indexed")
        self.assertEqual(src.chunk_count, 42)

    def test_add_source_marks_failed_when_ai_down(self):
        with mock.patch(VIEWS_REQ) as m:
            m.post.side_effect = Exception("AI down")
            r = self.admin_c.post(
                f"/api/courses/courses/{self.course.id}/corpus/sources/",
                {"title": "Intro", "book_stem": "b2", "source_type": "pdf"}, format="json",
            )
        self.assertEqual(r.status_code, 201)  # source still recorded
        self.assertEqual(CorpusSource.objects.get(book_stem="b2").index_status, "failed")


class DraftDescriptionTests(Base):
    def test_admin_only(self):
        r = self.stu_c.post(f"/api/courses/courses/{self.course.id}/draft_description/", {}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_proxies_ai_draft(self):
        with mock.patch(VIEWS_REQ) as m:
            m.post.return_value = _resp(200, {"description": "A great course.", "source": "llm"})
            r = self.admin_c.post(
                f"/api/courses/courses/{self.course.id}/draft_description/",
                {"topics": ["loops"]}, format="json",
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["description"], "A great course.")
        self.assertIn("/authoring/course-description", m.post.call_args.args[0])


class PathwayVersionsTests(Base):
    def test_admin_only(self):
        r = self.stu_c.get(f"/api/courses/courses/{self.course.id}/pathway/versions/?student_id=5")
        self.assertEqual(r.status_code, 403)

    def test_requires_student_id(self):
        r = self.admin_c.get(f"/api/courses/courses/{self.course.id}/pathway/versions/")
        self.assertEqual(r.status_code, 400)

    def test_proxies_versions(self):
        with mock.patch(VIEWS_REQ) as m:
            m.get.return_value = _resp(200, {"versions": [{"plan_version": 1, "is_current": True}]})
            r = self.admin_c.get(f"/api/courses/courses/{self.course.id}/pathway/versions/?student_id=5")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["versions"][0]["plan_version"], 1)
        self.assertIn("/pathway/versions", m.get.call_args.args[0])
