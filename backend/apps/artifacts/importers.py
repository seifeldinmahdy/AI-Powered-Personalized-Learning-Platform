"""
One-time importers: move the AI service's on-disk JSON history into the durable
artifact store (Batch 10a, stage 6).

Problem sets go first (ProblemSet + a historical ProblemSetAttempt per stored
submission, source="imported"), then labs (StudentArtifact, type=lab). Imported
rows carry plan_version = IMPORTED_PLAN_VERSION (0), a sentinel meaning
"pre-versioning" — real plan versions start at 1, so it never collides.

Unresolvable rows (legacy entries with no course_id, an enrollment/lesson that no
longer exists, etc.) are SKIPPED and recorded in a human-readable report — some
students' history failing to migrate is a silent failure otherwise, so the report
is the reviewable artifact, not a log line.

Idempotent: a problem set is skipped if its ps_uid already exists; a lab if a
lab artifact already exists for that (student, lesson, imported version).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.db import transaction

from apps.courses.models import Enrollment, Lesson
from .models import ProblemSet, ProblemSetAttempt, StudentArtifact

# Sentinel plan_version for imported (pre-versioning) artifacts. Real versions
# start at 1, so 0 is unambiguous and never collides with a generated plan.
IMPORTED_PLAN_VERSION = 0


def default_data_dir() -> Path:
    """The AI service data dir (repo_root/ai_service/data)."""
    return settings.BASE_DIR.parent / "ai_service" / "data"


class ImportReport:
    """Reviewable record of what migrated and what was skipped (and why)."""

    def __init__(self, kind: str):
        self.kind = kind
        self.migrated: list[tuple[str, str, str]] = []  # (student, key, detail)
        self.skipped: list[tuple[str, str, str]] = []    # (student, file, reason)

    def migrate(self, student, key, detail):
        self.migrated.append((str(student), str(key), str(detail)))

    def skip(self, student, file, reason):
        self.skipped.append((str(student), str(file), str(reason)))

    def summary_line(self) -> str:
        return f"{self.kind}: migrated={len(self.migrated)} skipped={len(self.skipped)}"

    def render_markdown(self) -> str:
        lines = [f"# Artifact import report — {self.kind}", "",
                 f"- migrated: **{len(self.migrated)}**",
                 f"- skipped: **{len(self.skipped)}**", ""]
        if self.skipped:
            lines += ["## Skip reasons (review these — history NOT migrated)", ""]
            for reason, n in Counter(r for _, _, r in self.skipped).most_common():
                lines.append(f"- {n}× {reason}")
            lines += ["", "| student | file | reason |", "|---|---|---|"]
            lines += [f"| {s} | {f} | {r} |" for s, f, r in self.skipped]
            lines.append("")
        if self.migrated:
            lines += ["## Migrated", "", "| student | key | detail |", "|---|---|---|"]
            lines += [f"| {s} | {k} | {d} |" for s, k, d in self.migrated]
            lines.append("")
        return "\n".join(lines)


def _resolve_enrollment(student_id, course_id):
    if not (str(student_id).isdigit() and str(course_id).isdigit()):
        return None
    return Enrollment.objects.filter(student_id=int(student_id), course_id=int(course_id)).first()


def _resolve_lesson(lesson_id):
    if not str(lesson_id).isdigit():
        return None
    return Lesson.objects.filter(pk=int(lesson_id)).first()


def import_problem_sets(data_dir, report: ImportReport, *, dry_run: bool = False) -> ImportReport:
    """Import problem-set JSON files into ProblemSet (+ imported attempts)."""
    root = Path(data_dir) / "problem_sets"
    files = sorted(root.rglob("*.json")) if root.exists() else []

    # Pass 1 — load + resolve; group valid files so generation_index is assigned
    # in submission order per (enrollment, lesson).
    groups: dict[tuple[int, int], list] = defaultdict(list)
    for path in files:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            report.skip("?", path.name, f"unreadable JSON: {e}")
            continue
        sid = str(d.get("student_id", ""))
        cid = str(d.get("course_id", ""))
        uid = d.get("problem_set_id")
        if not uid:
            report.skip(sid, path.name, "missing problem_set_id")
            continue
        if ProblemSet.objects.filter(ps_uid=uid).exists():
            report.skip(sid, path.name, "already imported")
            continue
        if not cid:
            report.skip(sid, path.name, "missing course_id (legacy)")
            continue
        enr = _resolve_enrollment(sid, cid)
        if not enr:
            report.skip(sid, path.name, f"no enrollment for course {cid}")
            continue
        lesson = _resolve_lesson(d.get("lesson_id"))
        if not lesson:
            report.skip(sid, path.name, f"lesson {d.get('lesson_id')} not found")
            continue
        groups[(enr.id, lesson.id)].append((d.get("generated_at", ""), d, enr, sid))

    # Pass 2 — create, assigning generation_index per group (latest is current).
    with transaction.atomic():
        for (enr_id, lesson_id), items in groups.items():
            items.sort(key=lambda t: t[0])  # submission/generation order
            last = len(items) - 1
            for idx, (_gen_at, d, enr, sid) in enumerate(items):
                ps = ProblemSet.objects.create(
                    enrollment=enr, student_id=enr.student_id, course_id=enr.course_id,
                    lesson_id=lesson_id, plan_version=IMPORTED_PLAN_VERSION,
                    generation_index=idx, ps_uid=d["problem_set_id"],
                    content_json={"questions": d.get("questions", [])},
                    superseded=(idx < last),
                )
                n_att = 0
                for qid, sub in (d.get("submissions", {}) or {}).items():
                    res = (sub or {}).get("result", {}) or {}
                    ProblemSetAttempt.objects.create(
                        problem_set=ps, question_id=qid, code=(sub or {}).get("code", ""),
                        evaluated_rubric=res.get("evaluated_rubric", []),
                        hints_used=int((sub or {}).get("hints_used", 0) or 0),
                        score=int(res.get("final_score", 0) or 0),
                        source=ProblemSetAttempt.IMPORTED,
                    )
                    n_att += 1
                report.migrate(sid, d["problem_set_id"],
                               f"gen{idx} superseded={idx < last} attempts={n_att}")
        if dry_run:
            transaction.set_rollback(True)
    return report


def import_labs(data_dir, report: ImportReport, *, dry_run: bool = False) -> ImportReport:
    """Import coding-lab JSON files into StudentArtifact(type=lab)."""
    root = Path(data_dir) / "coding_labs"
    files = sorted(root.glob("*.json")) if root.exists() else []

    with transaction.atomic():
        for path in files:
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                report.skip("?", path.name, f"unreadable JSON: {e}")
                continue
            lab_id = d.get("lab_id") or path.stem
            parts = lab_id.split("_")
            if len(parts) != 3 or parts[0] == "anonymous":
                report.skip(parts[0] if parts else "?", path.name,
                            f"unparseable lab_id {lab_id!r}")
                continue
            sid, cid, lid = parts
            enr = _resolve_enrollment(sid, cid)
            if not enr:
                report.skip(sid, path.name, f"no enrollment for course {cid}")
                continue
            lesson = _resolve_lesson(lid)
            if not lesson:
                report.skip(sid, path.name, f"lesson {lid} not found")
                continue
            if StudentArtifact.objects.filter(
                student_id=enr.student_id, artifact_type=StudentArtifact.LAB,
                lesson_id=lesson.id, plan_version=IMPORTED_PLAN_VERSION,
            ).exists():
                report.skip(sid, path.name, "already imported")
                continue
            status = "completed" if d.get("completed_at") else "generated"
            StudentArtifact.objects.create(
                enrollment=enr, student_id=enr.student_id, course_id=enr.course_id,
                artifact_type=StudentArtifact.LAB, lesson_id=lesson.id,
                plan_version=IMPORTED_PLAN_VERSION, generation_index=0,
                content_json=d, status=status,
            )
            report.migrate(sid, lab_id, f"status={status}")
        if dry_run:
            transaction.set_rollback(True)
    return report
