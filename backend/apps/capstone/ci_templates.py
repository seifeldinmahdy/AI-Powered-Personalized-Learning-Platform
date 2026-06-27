"""Deterministic per-language CI workflow generator for capstone repos.

Why deterministic (not LLM-written): a malformed ``ci.yml`` would block grading
for EVERY student in the course (the required ``ci`` check could never go green).
So the *language* is AI-suggested (a fuzzy task, admin-reviewed), but the YAML
itself is assembled from vetted templates here. The admin can still hand-edit the
result — it is stored as plain text on ``Capstone.ci_workflow``.

The generated workflow:
  - is named ``ci`` and its job is ``ci`` → the check-run name matches the
    branch-protection required context ("ci") and ``submit_for_grading``'s gate;
  - triggers on push + pull_request (so it runs on the student's ``work`` branch);
  - sets up the toolchain, installs deps if a manifest is present, then runs the
    capstone's ``run_command`` (or a sensible per-language build/smoke default).
"""

from __future__ import annotations

# alias → canonical language token
_ALIASES = {
    "py": "python", "python3": "python",
    "js": "javascript", "node": "javascript", "nodejs": "javascript",
    "ts": "typescript",
    "golang": "go",
    "c++": "cpp", "cplusplus": "cpp",
    "c#": "csharp", "cs": "csharp", "dotnet": "csharp", ".net": "csharp",
    "rb": "ruby", "rails": "ruby",
    "rs": "rust",
    "sh": "bash", "shell": "bash",
}


def normalize_language(language: str) -> str:
    lang = (language or "").strip().lower()
    return _ALIASES.get(lang, lang) or "python"


# Per-language: (setup_steps_yaml, default_run_command).
# setup steps are indented for placement directly under `steps:` (6-space "- ").
_SETUP_PYTHON = (
    "      - uses: actions/setup-python@v5\n"
    "        with:\n"
    "          python-version: '3.12'\n"
    "      - name: Install dependencies\n"
    "        run: |\n"
    "          python -m pip install --upgrade pip\n"
    "          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi\n"
)
_SETUP_NODE = (
    "      - uses: actions/setup-node@v4\n"
    "        with:\n"
    "          node-version: '20'\n"
    "      - name: Install dependencies\n"
    "        run: |\n"
    "          if [ -f package-lock.json ]; then npm ci; elif [ -f package.json ]; then npm install; fi\n"
)
_SETUP_JAVA = (
    "      - uses: actions/setup-java@v4\n"
    "        with:\n"
    "          distribution: 'temurin'\n"
    "          java-version: '21'\n"
)
_SETUP_GO = (
    "      - uses: actions/setup-go@v5\n"
    "        with:\n"
    "          go-version: '1.22'\n"
)
_SETUP_RUBY = (
    "      - uses: ruby/setup-ruby@v1\n"
    "        with:\n"
    "          ruby-version: '3.3'\n"
)
_SETUP_RUST = (
    "      - name: Install Rust\n"
    "        run: rustup toolchain install stable --profile minimal\n"
)
_SETUP_DOTNET = (
    "      - uses: actions/setup-dotnet@v4\n"
    "        with:\n"
    "          dotnet-version: '8.0.x'\n"
)
_SETUP_PHP = (
    "      - uses: shivammathur/setup-php@v2\n"
    "        with:\n"
    "          php-version: '8.3'\n"
)

# Defaults are smoke/build gates — admin overrides with run_command for real tests.
_SPECS: dict[str, tuple[str, str]] = {
    "python":     (_SETUP_PYTHON, "python -m compileall -q ."),
    "javascript": (_SETUP_NODE,   "npm test --if-present"),
    "typescript": (_SETUP_NODE,   "npx --yes tsc --noEmit || npm test --if-present"),
    "java":       (_SETUP_JAVA,   'javac $(find . -name "*.java")'),
    "go":         (_SETUP_GO,     "go build ./..."),
    "cpp":        ("",            'g++ -fsyntax-only $(find . -name "*.cpp" -o -name "*.cc")'),
    "c":          ("",            'gcc -fsyntax-only $(find . -name "*.c")'),
    "ruby":       (_SETUP_RUBY,   'find . -name "*.rb" -exec ruby -c {} \\;'),
    "php":        (_SETUP_PHP,    'find . -name "*.php" -exec php -l {} \\;'),
    "rust":       (_SETUP_RUST,   "cargo build"),
    "csharp":     (_SETUP_DOTNET, "dotnet build"),
    "bash":       ("",            'bash -n $(find . -name "*.sh")'),
}


def _run_block(command: str) -> str:
    """Render the run step as a YAML literal block (multi-line safe)."""
    lines = (command or "").splitlines() or [""]
    body = "\n".join("          " + ln for ln in lines)
    return "      - name: Build & run\n        run: |\n" + body + "\n"


def generate_ci_workflow(language: str, run_command: str = "") -> str:
    """Return a complete, valid ``.github/workflows/ci.yml`` for a language.

    ``run_command`` (the capstone's configured command) overrides the per-language
    default. Unknown languages fall back to the Python template.
    """
    lang = normalize_language(language)
    setup, default_run = _SPECS.get(lang, _SPECS["python"])
    run = (run_command or "").strip() or default_run
    # Cost controls (private repos consume billed Actions minutes, so keep usage
    # inside the org's free allowance):
    #   - trigger only on the student's `work` branch (+ PRs into work/main), not
    #     every branch/tag, so we don't burn minutes on incidental pushes;
    #   - cancel superseded in-flight runs for the same ref (no stacked builds);
    #   - hard 10-minute job timeout so a hung build can't drain the quota.
    return (
        "name: ci\n"
        "on:\n"
        "  push:\n"
        "    branches: [work]\n"
        "  pull_request:\n"
        "    branches: [work, main]\n"
        "concurrency:\n"
        "  group: ci-${{ github.ref }}\n"
        "  cancel-in-progress: true\n"
        "jobs:\n"
        "  ci:\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        f"{setup}"
        f"{_run_block(run)}"
    )
