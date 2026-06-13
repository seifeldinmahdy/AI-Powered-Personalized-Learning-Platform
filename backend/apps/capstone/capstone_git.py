"""
Server-side Git operations for capstone repos, via the GitHub Git Data API.

All calls authenticate with the installation token from github_app.py.
The token NEVER leaves the server — the browser only ever sees file contents,
trees, commit SHAs, and CI verdicts.

Commit strategy: atomic multi-file commit (blobs → tree → commit → move ref),
on a feature branch (never main), with retry on a stale ref.
"""

from __future__ import annotations

import base64
import logging
import re
from urllib.parse import urlparse

import requests

from .github_app import github_headers

logger = logging.getLogger(__name__)

API = "https://api.github.com"

# Guard rails
MAX_FILE_BYTES = 1_000_000          # 1 MB per file
MAX_FILES_PER_COMMIT = 100
_PATH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")


class GitError(Exception):
    """Raised for any failed Git Data API interaction or guard violation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_repo(repo_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub repo URL or 'owner/repo' string."""
    if not repo_url:
        raise GitError("Empty repo URL.")
    if repo_url.count("/") == 1 and "://" not in repo_url:
        owner, repo = repo_url.split("/", 1)
    else:
        path = urlparse(repo_url).path.strip("/")
        parts = path.split("/")
        if len(parts) < 2:
            raise GitError(f"Cannot parse owner/repo from {repo_url!r}.")
        owner, repo = parts[0], parts[1]
    return owner, repo.removesuffix(".git")


def _validate_path(path: str) -> None:
    """Reject traversal, absolute paths, and unexpected characters."""
    if not path or path.startswith("/") or "\\" in path:
        raise GitError(f"Invalid file path: {path!r}")
    if ".." in path.split("/"):
        raise GitError(f"Path traversal not allowed: {path!r}")
    if not _PATH_RE.match(path):
        raise GitError(f"Path contains disallowed characters: {path!r}")


def _get(url: str, **kwargs) -> requests.Response:
    return requests.get(url, headers=github_headers(), timeout=20, **kwargs)


def _post(url: str, json: dict) -> requests.Response:
    return requests.post(url, headers=github_headers(), json=json, timeout=20)


def _patch(url: str, json: dict) -> requests.Response:
    return requests.patch(url, headers=github_headers(), json=json, timeout=20)


# ---------------------------------------------------------------------------
# Branch helpers
# ---------------------------------------------------------------------------

def get_ref_sha(owner: str, repo: str, branch: str) -> str | None:
    """Return the commit SHA a branch points to, or None if it doesn't exist."""
    resp = _get(f"{API}/repos/{owner}/{repo}/git/ref/heads/{branch}")
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise GitError(f"get ref failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()["object"]["sha"]


def ensure_branch(repo_url: str, branch: str, base: str = "main") -> str:
    """
    Ensure `branch` exists; create it from `base` if missing.
    Returns the branch HEAD commit SHA.  Never touches `main` itself.
    """
    if branch == "main":
        raise GitError("Refusing to use 'main' as a feature branch.")
    owner, repo = parse_repo(repo_url)

    existing = get_ref_sha(owner, repo, branch)
    if existing:
        return existing

    base_sha = get_ref_sha(owner, repo, base)
    if not base_sha:
        # Fall back to the repo's default branch
        info = _get(f"{API}/repos/{owner}/{repo}")
        if info.status_code != 200:
            raise GitError(f"repo lookup failed ({info.status_code}).")
        default_branch = info.json().get("default_branch", "main")
        base_sha = get_ref_sha(owner, repo, default_branch)
        if not base_sha:
            raise GitError("Cannot resolve a base branch to fork from.")

    resp = _post(
        f"{API}/repos/{owner}/{repo}/git/refs",
        {"ref": f"refs/heads/{branch}", "sha": base_sha},
    )
    if resp.status_code not in (200, 201):
        raise GitError(f"branch create failed ({resp.status_code}): {resp.text[:200]}")
    return base_sha


# ---------------------------------------------------------------------------
# Read: tree + file
# ---------------------------------------------------------------------------

def get_tree(repo_url: str, branch: str) -> list[dict]:
    """Return the recursive file tree on a branch: [{path, type, size, sha}]."""
    owner, repo = parse_repo(repo_url)
    head_sha = get_ref_sha(owner, repo, branch)
    if not head_sha:
        raise GitError(f"Branch {branch!r} not found.")

    commit = _get(f"{API}/repos/{owner}/{repo}/git/commits/{head_sha}")
    if commit.status_code != 200:
        raise GitError(f"commit lookup failed ({commit.status_code}).")
    tree_sha = commit.json()["tree"]["sha"]

    tree = _get(f"{API}/repos/{owner}/{repo}/git/trees/{tree_sha}", params={"recursive": "1"})
    if tree.status_code != 200:
        raise GitError(f"tree lookup failed ({tree.status_code}).")
    data = tree.json()
    return [
        {
            "path": node["path"],
            "type": node["type"],          # "blob" | "tree"
            "size": node.get("size"),
            "sha": node["sha"],
        }
        for node in data.get("tree", [])
    ]


def get_file(repo_url: str, branch: str, path: str) -> dict:
    """Return {path, content (utf-8 text), sha, size} for one file."""
    _validate_path(path)
    owner, repo = parse_repo(repo_url)
    resp = _get(
        f"{API}/repos/{owner}/{repo}/contents/{path}",
        params={"ref": branch},
    )
    if resp.status_code == 404:
        raise GitError(f"File not found: {path!r}")
    if resp.status_code != 200:
        raise GitError(f"file fetch failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    if isinstance(data, list):
        raise GitError(f"{path!r} is a directory, not a file.")
    raw = base64.b64decode(data.get("content", "")) if data.get("encoding") == "base64" else b""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = ""  # binary file — return empty text, caller can warn
    return {"path": path, "content": text, "sha": data.get("sha", ""), "size": data.get("size", 0)}


# ---------------------------------------------------------------------------
# Ref read/move + repo bundle (used by the final grading flow)
# ---------------------------------------------------------------------------

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

# Text extensions we will pull into a grading bundle. Anything else (images,
# binaries, lockfiles we don't need) is skipped.
_BUNDLE_TEXT_EXTS = {
    "py", "js", "ts", "tsx", "jsx", "json", "md", "txt", "rst",
    "yml", "yaml", "toml", "cfg", "ini", "html", "css", "scss",
    "c", "cpp", "cc", "h", "hpp", "java", "go", "rs", "rb", "php",
    "sh", "bash", "sql", "r", "kt", "swift",
}
# Skip vendored / generated directories even if a blob slips through.
_BUNDLE_SKIP_DIRS = ("node_modules/", ".venv/", "venv/", "dist/", "build/", ".git/")
_BUNDLE_MAX_FILES = 80
_BUNDLE_MAX_TOTAL = 200_000      # ~200 KB of source is plenty for rubric judging


def head_sha(repo_url: str, branch: str) -> str:
    """Return the HEAD commit SHA of a branch (raises if the branch is gone)."""
    owner, repo = parse_repo(repo_url)
    sha = get_ref_sha(owner, repo, branch)
    if not sha:
        raise GitError(f"Branch {branch!r} not found.")
    return sha


def move_ref(repo_url: str, branch: str, sha: str, force: bool = False) -> str:
    """
    Point a branch ref at `sha`. Defaults to fast-forward only (force=False),
    so a non-ancestor target fails with 422 rather than rewriting history.

    Used to promote a CI-passed `work` commit onto `main` for final grading.
    `main` is the ONLY branch this is ever called on with a vetted, CI-green SHA.
    """
    owner, repo = parse_repo(repo_url)
    resp = _patch(
        f"{API}/repos/{owner}/{repo}/git/refs/heads/{branch}",
        {"sha": sha, "force": force},
    )
    if resp.status_code != 200:
        raise GitError(f"ref move failed ({resp.status_code}): {resp.text[:200]}")
    return sha


def _resolve_commit_sha(owner: str, repo: str, ref: str) -> str:
    """Accept either a 40-char SHA or a branch name and return a commit SHA."""
    if _SHA_RE.match(ref or ""):
        return ref
    sha = get_ref_sha(owner, repo, ref)
    if not sha:
        raise GitError(f"Cannot resolve ref {ref!r}.")
    return sha


def read_repo_bundle(repo_url: str, ref: str) -> str:
    """
    Read a repo's text files at `ref` (SHA or branch) into a single in-memory
    bundle string for rubric grading. The bundle is NEVER persisted — the
    platform stores only repo_url + commit_sha + results_json.

    Binary/large/vendored files are skipped; total size is capped.
    """
    owner, repo = parse_repo(repo_url)
    sha = _resolve_commit_sha(owner, repo, ref)

    commit = _get(f"{API}/repos/{owner}/{repo}/git/commits/{sha}")
    if commit.status_code != 200:
        raise GitError(f"commit lookup failed ({commit.status_code}).")
    tree_sha = commit.json()["tree"]["sha"]

    tree = _get(f"{API}/repos/{owner}/{repo}/git/trees/{tree_sha}", params={"recursive": "1"})
    if tree.status_code != 200:
        raise GitError(f"tree lookup failed ({tree.status_code}).")

    blobs = [n for n in tree.json().get("tree", []) if n.get("type") == "blob"]
    parts: list[str] = []
    total = 0
    count = 0
    for node in sorted(blobs, key=lambda x: x.get("path", "")):
        if count >= _BUNDLE_MAX_FILES or total >= _BUNDLE_MAX_TOTAL:
            break
        path = node.get("path", "")
        if any(skip in path for skip in _BUNDLE_SKIP_DIRS):
            continue
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext not in _BUNDLE_TEXT_EXTS:
            continue
        if (node.get("size") or 0) > MAX_FILE_BYTES:
            continue
        blob = _get(f"{API}/repos/{owner}/{repo}/git/blobs/{node['sha']}")
        if blob.status_code != 200:
            continue
        data = blob.json()
        raw = base64.b64decode(data.get("content", "")) if data.get("encoding") == "base64" else b""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue  # binary file
        chunk = f"\n# ===== {path} =====\n{text}\n"
        parts.append(chunk)
        total += len(chunk)
        count += 1

    return "".join(parts)


# ---------------------------------------------------------------------------
# Write: atomic multi-file commit
# ---------------------------------------------------------------------------

def commit(
    repo_url: str,
    branch: str,
    changed_files: list[dict],
    message: str,
    author_name: str,
    author_email: str = "",
    coauthor_trailer: str = "",
) -> str:
    """
    Atomically commit multiple changed files to a feature branch.

    changed_files: [{path, content, deleted?}]
    Returns the new commit SHA.  Retries once on a stale ref (concurrent commit).
    """
    if branch == "main":
        raise GitError("Refusing to commit to 'main'. Use a feature branch.")
    if not changed_files:
        raise GitError("No changed files supplied.")
    if len(changed_files) > MAX_FILES_PER_COMMIT:
        raise GitError(f"Too many files in one commit (max {MAX_FILES_PER_COMMIT}).")

    for f in changed_files:
        _validate_path(f.get("path", ""))
        content = f.get("content", "") or ""
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise GitError(f"File too large: {f['path']!r} (max {MAX_FILE_BYTES} bytes).")

    owner, repo = parse_repo(repo_url)

    # Ensure the feature branch exists (forked from main) before committing.
    ensure_branch(repo_url, branch)

    # Step 3: create blobs once (independent of ref state).
    tree_entries: list[dict] = []
    for f in changed_files:
        path = f["path"]
        if f.get("deleted"):
            tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            continue
        blob = _post(
            f"{API}/repos/{owner}/{repo}/git/blobs",
            {"content": f.get("content", ""), "encoding": "utf-8"},
        )
        if blob.status_code not in (200, 201):
            raise GitError(f"blob create failed ({blob.status_code}): {blob.text[:200]}")
        tree_entries.append(
            {"path": path, "mode": "100644", "type": "blob", "sha": blob.json()["sha"]}
        )

    full_message = message.strip() or "Update from in-platform editor"
    if coauthor_trailer:
        full_message = f"{full_message}\n\n{coauthor_trailer}"

    # Steps 4–6 with retry on stale ref.
    last_err = ""
    for attempt in range(3):
        head_sha = get_ref_sha(owner, repo, branch)
        if not head_sha:
            raise GitError(f"Branch {branch!r} vanished mid-commit.")

        base_commit = _get(f"{API}/repos/{owner}/{repo}/git/commits/{head_sha}")
        if base_commit.status_code != 200:
            raise GitError(f"base commit lookup failed ({base_commit.status_code}).")
        base_tree_sha = base_commit.json()["tree"]["sha"]

        new_tree = _post(
            f"{API}/repos/{owner}/{repo}/git/trees",
            {"base_tree": base_tree_sha, "tree": tree_entries},
        )
        if new_tree.status_code not in (200, 201):
            raise GitError(f"tree create failed ({new_tree.status_code}): {new_tree.text[:200]}")
        new_tree_sha = new_tree.json()["sha"]

        author = {"name": author_name or "student", "email": author_email or f"{author_name or 'student'}@users.noreply.github.com"}
        new_commit = _post(
            f"{API}/repos/{owner}/{repo}/git/commits",
            {
                "message": full_message,
                "tree": new_tree_sha,
                "parents": [head_sha],
                "author": author,
            },
        )
        if new_commit.status_code not in (200, 201):
            raise GitError(f"commit create failed ({new_commit.status_code}): {new_commit.text[:200]}")
        new_commit_sha = new_commit.json()["sha"]

        # Move the feature branch ref (non-force; fast-forward only).
        move = _patch(
            f"{API}/repos/{owner}/{repo}/git/refs/heads/{branch}",
            {"sha": new_commit_sha, "force": False},
        )
        if move.status_code == 200:
            return new_commit_sha

        # 422 = ref moved under us (stale). Re-read HEAD and replay 4–6.
        last_err = f"{move.status_code}: {move.text[:200]}"
        logger.warning("Stale ref on attempt %s for %s/%s: %s", attempt + 1, owner, repo, last_err)

    raise GitError(f"commit failed after retries: {last_err}")


# ---------------------------------------------------------------------------
# CI verdict: Check Runs API
# ---------------------------------------------------------------------------

def get_check_runs(repo_url: str, sha: str) -> dict:
    """
    Read CI check runs for a commit SHA.

    Returns {status, conclusion, reason} where:
      status     = queued | in_progress | completed
      conclusion = success | failure | neutral | None
      reason     = human-readable summary parsed from each run's Step Summary
    """
    owner, repo = parse_repo(repo_url)
    resp = _get(f"{API}/repos/{owner}/{repo}/commits/{sha}/check-runs")
    if resp.status_code != 200:
        raise GitError(f"check-runs lookup failed ({resp.status_code}): {resp.text[:200]}")
    runs = resp.json().get("check_runs", [])

    if not runs:
        return {"status": "queued", "conclusion": None, "reason": "No CI checks have started yet."}

    all_completed = all(r.get("status") == "completed" for r in runs)
    conclusions = [r.get("conclusion") for r in runs if r.get("conclusion")]

    if not all_completed:
        return {"status": "in_progress", "conclusion": None, "reason": "CI checks are still running…"}

    overall = "success" if conclusions and all(c == "success" for c in conclusions) else "failure"

    # Reason = the CI Step Summary written by ci.yml (output.summary / output.text).
    reason_parts: list[str] = []
    for r in runs:
        output = r.get("output") or {}
        summary = (output.get("summary") or "").strip()
        if summary:
            reason_parts.append(f"{r.get('name', 'check')}: {summary}")
        elif r.get("conclusion") and r.get("conclusion") != "success":
            reason_parts.append(f"{r.get('name', 'check')}: {r.get('conclusion')}")
    reason = "\n".join(reason_parts) or ("All checks passed." if overall == "success" else "One or more checks failed.")

    return {"status": "completed", "conclusion": overall, "reason": reason}


# ---------------------------------------------------------------------------
# Contribution checks: commit history authorship
# ---------------------------------------------------------------------------

def list_commit_authors(repo_url: str, branch: str, max_commits: int = 100) -> list[dict]:
    """
    Return [{sha, author_login, author_name, files_changed, message}] for the
    branch's commit history (most recent first), used for per-member checks.
    """
    owner, repo = parse_repo(repo_url)
    resp = _get(
        f"{API}/repos/{owner}/{repo}/commits",
        params={"sha": branch, "per_page": min(max_commits, 100)},
    )
    if resp.status_code != 200:
        raise GitError(f"commit list failed ({resp.status_code}): {resp.text[:200]}")
    out = []
    for c in resp.json():
        author = c.get("author") or {}
        commit_meta = c.get("commit", {})
        out.append({
            "sha": c.get("sha", ""),
            "author_login": author.get("login", ""),
            "author_name": commit_meta.get("author", {}).get("name", ""),
            "message": commit_meta.get("message", "").splitlines()[0] if commit_meta.get("message") else "",
        })
    return out


def summarize_contributions(repo_url: str, branch: str, member_usernames: list[str]) -> dict:
    """
    Per-member contribution summary derived from commit authorship.
    Returns {username: {commit_count, meaningful}} where meaningful = commit_count >= 1.
    """
    try:
        commits = list_commit_authors(repo_url, branch)
    except GitError:
        logger.exception("Could not list commits for contribution check.")
        return {u: {"commit_count": 0, "meaningful": False} for u in member_usernames}

    counts: dict[str, int] = {u.lower(): 0 for u in member_usernames}
    for c in commits:
        login = (c.get("author_login") or "").lower()
        name = (c.get("author_name") or "").lower()
        for u in member_usernames:
            ul = u.lower()
            if ul and (ul == login or ul == name):
                counts[ul] += 1

    return {
        u: {"commit_count": counts.get(u.lower(), 0), "meaningful": counts.get(u.lower(), 0) >= 1}
        for u in member_usernames
    }
