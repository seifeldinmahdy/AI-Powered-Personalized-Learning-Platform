# GitHub App Setup for Capstone Repos

## Overview

The platform uses a GitHub App (not a PAT) to:
- Create public student repos under your org from a template
- Set branch protection on `main`
- Invite students as collaborators
- Receive `check_suite` webhook events to track CI status

All repos are **public** — GitHub Actions runners are free and unlimited for public repos.
The platform stores only `repo_url + commit_sha + results_json`, never cloned code.

---

## 1. Create a GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set:
   - **App name**: `my-platform-capstone` (or any unique name)
   - **Homepage URL**: your platform URL
   - **Webhook URL**: `https://your-backend.com/api/capstone/github-webhook/`
   - **Webhook secret**: generate a random string (32+ chars) — store as `GITHUB_WEBHOOK_SECRET`
3. **Permissions**:
   - Repository: Contents → Read & Write
   - Repository: Administration → Read & Write
   - Repository: Checks → Read
   - Repository: Metadata → Read
4. **Subscribe to events**:
   - `check_suite`
   - `push`
5. Click **Create GitHub App**
6. Note the **App ID** → set as `GITHUB_APP_ID`
7. Generate a **private key** (PEM) → paste content as `GITHUB_APP_PRIVATE_KEY` in `.env`
   - Flatten newlines: `awk 'NF {printf "%s\\n", $0}' private-key.pem` → paste the single-line result

---

## 2. Install the App on your Organization

1. Go to the App settings → **Install App** → select your org
2. Choose **All repositories** (or restrict to repos matching `capstone-*`)
3. After install, note the **Installation ID** from the URL:
   `github.com/organizations/<org>/settings/installations/<INSTALLATION_ID>`
4. Set `GITHUB_APP_INSTALLATION_ID` in `.env`

---

## 3. Create a Template Repository

Create a public repo `<org>/capstone-template` with at least:

```
.github/
  workflows/
    ci.yml
README.md
```

Set it as a **Template repository** in its settings.

### Example `ci.yml`

> The job name **must** be `ci` (referenced by branch-protection `required_status_checks.contexts`).
> The platform reads the **Check Run Step Summary** (`$GITHUB_STEP_SUMMARY`) as the human-readable
> verdict reason shown in the in-platform workspace, so always write a summary line.

```yaml
name: CI

on:
  push:
    branches: ["**"]      # run on every branch, including the student's 'work' branch
  pull_request:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        id: tests
        run: |
          set -o pipefail
          python -m pytest --tb=short -q | tee pytest.out
      - name: Write verdict summary
        if: always()
        run: |
          if [ "${{ job.status }}" = "success" ]; then
            echo "✅ All tests passed." >> "$GITHUB_STEP_SUMMARY"
          else
            echo "❌ Tests failed:" >> "$GITHUB_STEP_SUMMARY"
            tail -n 20 pytest.out >> "$GITHUB_STEP_SUMMARY" || true
          fi
```

### In-platform IDE flow (Batch 3)

Students never touch the GitHub token. The browser only sends file contents and
commit messages to the platform backend, which performs all Git operations
server-side via the Git Data API:

1. **Workspace** (`/course/:id/capstone/workspace`) — Monaco multi-file editor; the
   file tree and file contents come from `GET …/tree` and `GET …/file` (server-side reads).
2. **Commit** — `POST …/commit` runs blobs → tree → commit → move-ref on the student's
   **`work`** feature branch (never `main`), with retry on a stale ref.
3. **Verdict** — `GET …/commit-status/:sha` reads the Check Runs API and returns the
   parsed Step Summary as the reason (✅ Approved / ❌ Rejected).
4. **Run** — `POST …/run` executes the uncommitted files in the AI-service sandbox for
   local feedback only (the official verdict is always CI).

Per-commit CI = continuous feedback. The PR-to-`main` merge (branch protection) = final acceptance.

Set the template repo slug as `GITHUB_TEMPLATE_REPO` (e.g. `my-org/capstone-template`).

---

## 4. Environment Variables

Add to `backend/.env`:

```dotenv
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\nMIIEo...\n-----END RSA PRIVATE KEY-----
GITHUB_APP_INSTALLATION_ID=12345678
GITHUB_ORG=my-org
GITHUB_WEBHOOK_SECRET=super-random-secret-value
INTERNAL_SERVICE_KEY=another-random-secret
```

> **Never** put these in frontend code, environment variable names with `VITE_` prefix,
> or commit them to version control.

---

## 5. Verify Setup

```bash
# From backend venv:
python -c "
from apps.capstone.github_app import mint_app_jwt, get_installation_token
print('JWT:', mint_app_jwt()[:40], '...')
print('Token:', get_installation_token()[:10], '...')
"
```

---

## 6. Webhook Signature Verification

The platform verifies every webhook with HMAC-SHA256:

```
X-Hub-Signature-256: sha256=<hex-digest>
```

Computed with `GITHUB_WEBHOOK_SECRET` as the key and the raw request body as the message.
Any request failing verification receives HTTP 403.

---

## 7. Student Workflow

1. Student opens capstone page, clicks **"Get my repo"**
2. Platform calls `POST /api/capstone/<id>/provision-repo/` → creates `<org>/capstone-<id>-<username>`
3. Student receives repo URL, clones it, pushes work
4. Student clicks **"Submit from repo"** → records `repo_url + commit_sha`
5. GitHub Actions CI runs on push → sends `check_suite` webhook on completion
6. Platform records CI result and marks submission `completed` or `failed`
7. Admin can also trigger evaluation from the archive upload path
