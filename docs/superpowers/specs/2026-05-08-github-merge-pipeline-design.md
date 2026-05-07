# DKE Design Spec — GitHub Merge Pipeline (CI)
**Date:** 2026-05-08
**Status:** Approved

---

## 1. Problem Statement

The DKE repository has no automated quality gate on pull requests. Code with lint errors, type violations, security issues, or broken builds can be merged freely. This spec defines a GitHub Actions CI pipeline that runs on every PR and blocks merge until all checks pass.

---

## 2. Scope

### In scope
- GitHub Actions workflow (`.github/workflows/ci.yml`) triggered on every PR regardless of target branch
- Backend checks: Ruff lint, Mypy type-check, Bandit SAST, pip-audit, Pytest (mocked DB)
- Frontend checks: ESLint, TypeScript check (`tsc --noEmit`), npm audit, Next.js build
- Secrets scan: Gitleaks full-history scan on every PR
- GitHub branch ruleset configuration to enforce the `ci` job as a required status check

### Out of scope
- Scheduled nightly runs (can be added later as a separate workflow)
- Deployment pipeline (separate from merge gating)
- Code coverage reporting or coverage thresholds
- Performance benchmarks

---

## 3. Architecture

Single GitHub Actions job (`ci`) on `ubuntu-latest`. All steps run sequentially — a failure at any step halts the job immediately (fail-fast).

```
PR opened / updated
        ↓
GitHub Actions: ci job (ubuntu-latest, Python 3.12, Node 20)
        ↓
[1] Checkout (full history for gitleaks)
[2] Set up Python 3.12 (pip cache)
[3] Set up Node 20 (npm cache)
        ↓
── Secrets ──────────────────────────────
[4] Gitleaks — hardcoded secrets scan
        ↓
── Backend ──────────────────────────────
[5] pip install -r requirements.txt
[6] Ruff lint
[7] Mypy type-check
[8] Bandit SAST (-ll: MEDIUM + HIGH only)
[9] pip-audit dependency CVE scan
[10] Pytest (DB layer mocked)
        ↓
── Frontend ─────────────────────────────
[11] npm ci
[12] ESLint
[13] tsc --noEmit
[14] npm audit (--audit-level=high)
[15] Next.js build
        ↓
All pass → PR merge unblocked
Any fail → PR merge blocked
```

**Step ordering rationale:** Cheapest/fastest checks run first. Secrets scan runs before any dependency installation. Lint and type checks run before slower test and build steps.

---

## 4. Workflow File

**File:** `.github/workflows/ci.yml`

> **Note:** `working-directory` values in the YAML (`dke` for backend, `frontend` for Next.js) must match the actual directory names in the repo. Adjust if the frontend lives at a different path (e.g. `frontend/`, `web/`, or the repo root).

```yaml
name: CI

on:
  pull_request:

jobs:
  ci:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # required for gitleaks full history scan

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Set up Node 20
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      # ── Secrets Scan ──────────────────────────────────────────
      - name: Gitleaks — scan for hardcoded secrets
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      # ── Backend ───────────────────────────────────────────────
      - name: Install backend dependencies
        run: pip install -r requirements.txt
        working-directory: dke

      - name: Ruff lint
        run: ruff check backend/
        working-directory: dke

      - name: Mypy type-check
        run: mypy backend/
        working-directory: dke

      - name: Bandit — Python security scan
        run: bandit -r backend/ -ll
        working-directory: dke

      - name: pip-audit — dependency vulnerability scan
        run: pip-audit
        working-directory: dke

      - name: Pytest
        run: pytest backend/tests/ -v --tb=short
        working-directory: dke

      # ── Frontend ──────────────────────────────────────────────
      - name: Install frontend dependencies
        run: npm ci
        working-directory: frontend

      - name: ESLint
        run: npm run lint
        working-directory: frontend

      - name: TypeScript check
        run: npx tsc --noEmit
        working-directory: frontend

      - name: npm audit — dependency vulnerability scan
        run: npm audit --audit-level=high
        working-directory: frontend

      - name: Next.js build
        run: npm run build
        working-directory: frontend
```

---

## 5. Security Checks

| Check | Tool | Severity threshold | What it catches |
|---|---|---|---|
| Secrets in code/history | `gitleaks` v2 | Any | API keys, tokens, passwords committed to git |
| Python SAST | `bandit` | MEDIUM + HIGH (`-ll`) | Insecure patterns: eval, subprocess injection, hardcoded passwords |
| Python dep CVEs | `pip-audit` | Any | Known CVEs in installed Python packages |
| Node dep CVEs | `npm audit` | HIGH + CRITICAL (`--audit-level=high`) | Known CVEs in npm packages |

**Thresholds rationale:**
- Bandit LOW severity is suppressed (`-ll`) to avoid noise from common patterns like `assert` usage in tests
- npm audit blocks only HIGH/CRITICAL — moderate CVEs in transitive deps are too common to be actionable as a hard gate

---

## 6. Mocked DB Strategy

No PostgreSQL service container is used. The SQLAlchemy session dependency (`get_db`) is patched at the `conftest.py` level using `unittest.mock`.

**`backend/tests/conftest.py`:**
```python
from unittest.mock import MagicMock, patch
import pytest

@pytest.fixture(autouse=True)
def mock_db():
    with patch("backend.db.postgres.get_db") as mock:
        mock.return_value = MagicMock()
        yield mock
```

Per-test DB responses are configured inline:
```python
def test_list_bookmarks(client, mock_db):
    mock_db.return_value.query.return_value.all.return_value = []
    response = client.get("/bookmarks")
    assert response.status_code == 200
```

This approach tests API routing, request validation, and business logic without requiring a live database. It does not validate SQL correctness — that is acceptable for CI; SQL is validated in local integration tests.

---

## 7. Branch Protection Setup

After the workflow file is merged, configure a branch ruleset in GitHub:

**Settings → Branches → Add ruleset:**

| Setting | Value |
|---|---|
| Ruleset name | `PR merge gate` |
| Target | All branches |
| Require status checks to pass | ✅ |
| Required check | `ci` |
| Require branches to be up to date before merging | ✅ |
| Block force pushes | ✅ |
| Require linear history | Recommended |

This is a one-time manual step. All PRs against any branch are then automatically gated.

---

## 8. Tools Added to Backend Dependencies

The following tools must be added to `dke/requirements.txt` (or a `requirements-dev.txt` if dev deps are split):

```
ruff
mypy
bandit
pip-audit
pytest
pytest-anyio        # if async routes are tested
httpx               # for FastAPI TestClient
```

---

## 9. Verification Checklist

1. Open a PR with a deliberate Ruff lint error → verify CI fails at the Ruff step and merge is blocked
2. Open a PR with a hardcoded API key string → verify Gitleaks fails and merge is blocked
3. Open a PR with a Mypy type error → verify CI fails at the Mypy step
4. Open a PR where all checks pass → verify the `ci` status check turns green and merge is unblocked
5. In GitHub Settings → Branches → confirm the `PR merge gate` ruleset shows `ci` as a required check
6. Attempt a force push to a protected branch → verify it is blocked
