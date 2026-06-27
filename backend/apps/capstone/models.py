from django.db import models


class Capstone(models.Model):
    SPEC_MODE_CHOICES = [
        ("admin_defined", "Admin-defined"),
        ("student_proposed", "Student-proposed"),
    ]
    TEAM_MODE_CHOICES = [
        ("solo", "Solo"),
        ("team", "Team"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    ]
    # How the PASS/FAIL verdict is computed (always in Python, never by the LLM).
    PASS_POLICY_CHOICES = [
        ("all_core", "All core criteria must pass"),
    ]

    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="capstones"
    )
    title = models.CharField(max_length=200)
    spec_mode = models.CharField(
        max_length=20, choices=SPEC_MODE_CHOICES, default="admin_defined"
    )
    team_mode = models.CharField(
        max_length=10, choices=TEAM_MODE_CHOICES, default="solo"
    )
    # Primary programming language of the capstone (the course's language). Drives
    # the local "Run" sandbox defaults (interpreter + default entry file) and is
    # advisory metadata for the UI. Grading is language-agnostic (the LLM judge
    # reads the code bundle), so this never affects the rubric verdict.
    language = models.CharField(
        max_length=30, default="python",
        help_text="e.g. python, javascript, typescript, java, go, cpp, ruby, php.",
    )
    team_cap = models.PositiveIntegerField(default=4)
    deadline = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    pass_policy = models.CharField(
        max_length=20, choices=PASS_POLICY_CHOICES, default="all_core",
        help_text="Rule for the PASS/FAIL verdict. 'all_core' = every core criterion must pass.",
    )
    brief_text = models.TextField(blank=True)
    github_template_repo = models.CharField(max_length=300, blank=True)
    # Configurable run command stored on the capstone for the CI template
    run_command = models.CharField(max_length=500, blank=True)
    # Canonical CI workflow (.github/workflows/ci.yml) for this course, seeded
    # verbatim into every student's repo at provisioning so the required "ci"
    # check is identical for all students. Authored once by the admin (AI-suggested
    # language → generated YAML → review/edit). When blank and no template repo is
    # set, a language-appropriate default is generated at provision time.
    ci_workflow = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "capstones"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.course})"

    def save(self, *args, **kwargs):
        # Keep team_mode and team_cap coherent: a solo capstone is, by definition,
        # a team of one. This is the belt-and-suspenders guard behind the API-level
        # serializer validation, so no code path can persist a solo capstone with a
        # cap > 1 (or a team capstone with a cap < 2).
        if self.team_mode == "solo":
            self.team_cap = 1
        elif self.team_mode == "team" and (self.team_cap or 0) < 2:
            self.team_cap = 2
        super().save(*args, **kwargs)


class CapstoneRubricItem(models.Model):
    CATEGORY_CHOICES = [
        ("core", "Core"),
        ("stretch", "Stretch"),
    ]

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="rubric_items"
    )
    text = models.TextField()
    # Hierarchical decomposition (mirrors the problem-set rubric → criterion →
    # binary checks structure). Each criterion is judged through its atomic checks:
    # [{"id": "<stable>", "text": "<binary yes/no sub-check>"}]. A criterion PASSES
    # iff every check passes; the score gives partial credit per check passed.
    # Empty list = legacy criterion judged as a single coarse yes/no on `text`.
    checks = models.JSONField(
        default=list, blank=True,
        help_text="Atomic binary sub-checks: [{id, text}]. Criterion passes iff all checks pass.",
    )
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default="core")
    clo = models.ForeignKey(
        "courses.CourseLearningOutcome",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="capstone_items",
    )
    concept = models.ForeignKey(
        "courses.Concept",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="capstone_items",
    )
    weight = models.PositiveIntegerField(default=1)
    # 1 = applies to all (solo + team); 2 = teams of 2+; etc.
    min_team_size = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "capstone_rubric_items"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.capstone} — {self.text[:60]}"


class CapstoneProposal(models.Model):
    APPROVAL_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="proposals"
    )
    student = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="capstone_proposals"
    )
    # Set for TEAM-mode capstones: the proposal belongs to the whole team (one
    # shared idea the team agrees on), authored by `student`. Null for solo, where
    # the proposal is per-student. This is what lets a team "propose an idea"
    # coherently instead of every member filing a separate competing proposal.
    team = models.ForeignKey(
        "Team", null=True, blank=True, on_delete=models.CASCADE, related_name="proposals"
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    planned_features = models.JSONField(default=list)
    # Team-mode agreement: which members have agreed to THIS shared idea. The
    # author auto-agrees on submit; the proposal is only the team's official one
    # (and reaches the admin / unlocks work) once every member has agreed — so one
    # member can't commit the team to an idea the others didn't sign off on.
    agreed_members = models.ManyToManyField(
        "users.User", related_name="agreed_capstone_proposals", blank=True
    )
    approval_status = models.CharField(
        max_length=10, choices=APPROVAL_CHOICES, default="pending"
    )
    admin_feedback = models.TextField(blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "capstone_proposals"
        unique_together = [["capstone", "student"]]
        constraints = [
            # At most one proposal per team (the shared team idea).
            models.UniqueConstraint(
                fields=["capstone", "team"],
                condition=models.Q(team__isnull=False),
                name="uniq_team_proposal",
            ),
        ]
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.student} → {self.capstone}: {self.approval_status}"


class Team(models.Model):
    """A team of students collaborating on a team-mode capstone."""

    STATUS_CHOICES = [
        ("forming", "Forming"),
        ("active", "Active"),
        ("submitted", "Submitted"),
        ("disbanded", "Disbanded"),
    ]

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="teams"
    )
    name = models.CharField(max_length=120, blank=True)
    members = models.ManyToManyField(
        "users.User", related_name="capstone_teams", blank=True
    )
    # Members who have ACCEPTED a proposed match. A matchmade team starts in
    # 'forming' with members set but confirmations empty; it only becomes 'active'
    # once every member accepts. This is what prevents force-assignment — a student
    # matched with someone they don't want can decline instead of being stuck.
    confirmed_members = models.ManyToManyField(
        "users.User", related_name="confirmed_capstone_teams", blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="forming")
    # ONE shared GitHub repo per team (team-mode collaboration happens here, rather
    # than every member provisioning a separate repo). Provisioned once for the
    # team; all members are invited as collaborators. Solo capstones don't use this.
    repo_url = models.URLField(blank=True)
    branch = models.CharField(max_length=100, default="work")
    # Advisory suggested division of labor (lead/support per area). Text only —
    # never feeds scoring, the verdict, or contribution checks. Cached; regenerated
    # on membership change or an explicit refresh (see apps.capstone.team_roles).
    role_advice = models.JSONField(default=dict, blank=True)
    role_advice_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "capstone_teams"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name or f'Team {self.pk}'} ({self.capstone})"


class MatchmakingQueueEntry(models.Model):
    """A student waiting to be matched into a team for a team-mode capstone."""

    STATUS_CHOICES = [
        ("waiting", "Waiting"),
        ("matched", "Matched"),
        ("expired", "Expired"),
    ]

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="queue_entries"
    )
    student = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="capstone_queue_entries"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="waiting")
    # After this moment, the matchmaker may form the best available team
    # (even a team of 1) so the queue never deadlocks.
    fill_window_expires_at = models.DateTimeField(null=True, blank=True)
    # User ids this student has declined (or been declined by). The matchmaker
    # won't re-propose a team pairing these users, so declining isn't a no-op loop.
    declined_user_ids = models.JSONField(default=list, blank=True)
    team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="queue_entries"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "capstone_matchmaking_queue"
        unique_together = [["capstone", "student"]]
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.student} → {self.capstone} ({self.status})"


class CapstoneSubmission(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("evaluating", "Evaluating"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]
    # Pipeline status above is about WHETHER grading ran; verdict is the
    # PASS/FAIL outcome computed in Python from the binary rubric results.
    VERDICT_CHOICES = [
        ("pending", "Pending"),
        ("pass", "Pass"),
        ("fail", "Fail"),
    ]

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="submissions"
    )
    enrollment = models.ForeignKey(
        "courses.Enrollment",
        on_delete=models.CASCADE,
        related_name="capstone_submissions",
    )
    proposal = models.ForeignKey(
        CapstoneProposal,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submissions",
    )
    # Nullable team FK — set for team-mode capstones (Batch 3).
    team = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submissions",
    )
    repo_url = models.URLField(blank=True)
    # Feature branch the student works/commits on. Never "main".
    branch = models.CharField(max_length=100, default="work")
    latest_commit_sha = models.CharField(max_length=40, blank=True)
    github_username = models.CharField(max_length=100, blank=True)
    # {rubric_item_id: {passed: bool, weight: int, evidence: str}}
    results = models.JSONField(default=dict)
    score = models.FloatField(null=True, blank=True)
    # PASS/FAIL computed in Python (LLM never decides this). 'pending' until graded.
    verdict = models.CharField(max_length=10, choices=VERDICT_CHOICES, default="pending")
    feedback = models.TextField(blank=True)
    # Per-member contribution summary (team mode); derived from commit history.
    contributions = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    # Idempotent grading bookkeeping: re-submitting re-scores the submission but
    # must never multiply rewards. Rewards (capstone XP + concept-mastery EMA +
    # course completion) are granted exactly once, on the FIRST PASS verdict;
    # mastery_applied guards that bundle, xp_awarded records what was granted.
    xp_awarded = models.PositiveIntegerField(default=0)
    mastery_applied = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    # Grading state machine (recovery for stuck "evaluating" jobs). A grade runs
    # in a worker thread; if the process dies mid-grade the row would otherwise
    # stay "evaluating" forever. grading_started_at stamps when the current
    # attempt began; recover_stuck_grades() re-queues (or fails) rows whose
    # attempt has exceeded the timeout. grading_attempts bounds the retries.
    grading_started_at = models.DateTimeField(null=True, blank=True)
    grading_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "capstone_submissions"
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.enrollment.student} — {self.capstone} ({self.status})"


class CapstoneAssistQuota(models.Model):
    """
    Tracks AI-assist usage credits for a student (or team) on a capstone.
    Decremented per assist request; blocks at zero; resets each period.
    """

    PERIOD_CHOICES = [
        ("daily", "Daily"),
        ("weekly", "Weekly"),
    ]

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="assist_quotas"
    )
    student = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="capstone_assist_quotas",
    )
    team = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="assist_quotas",
    )
    period = models.CharField(max_length=10, choices=PERIOD_CHOICES, default="daily")
    used = models.PositiveIntegerField(default=0)
    limit = models.PositiveIntegerField(default=10)
    period_start = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "capstone_assist_quotas"
        unique_together = [["capstone", "student"]]

    def __str__(self):
        owner = self.student or self.team
        return f"{owner} — {self.used}/{self.limit} ({self.period})"

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class CapstoneAssistLog(models.Model):
    """Audit log of every AI-assist call; reliance feeds back into mastery."""

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="assist_logs"
    )
    student = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="capstone_assist_logs"
    )
    concept = models.ForeignKey(
        "courses.Concept",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="capstone_assist_logs",
    )
    question = models.TextField(blank=True)
    response_excerpt = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "capstone_assist_logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student} assist on {self.capstone} @ {self.created_at:%Y-%m-%d}"
