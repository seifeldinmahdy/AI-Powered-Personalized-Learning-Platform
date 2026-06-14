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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "capstones"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.course})"


class CapstoneRubricItem(models.Model):
    CATEGORY_CHOICES = [
        ("core", "Core"),
        ("stretch", "Stretch"),
    ]

    capstone = models.ForeignKey(
        Capstone, on_delete=models.CASCADE, related_name="rubric_items"
    )
    text = models.TextField()
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
    title = models.CharField(max_length=200)
    description = models.TextField()
    planned_features = models.JSONField(default=list)
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="forming")
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
