# DKE Design Spec — Continuous Deployment Pipeline
**Date:** 2026-05-11
**Status:** Approved

---

## 1. Problem Statement

The DKE project has no automated deployment pipeline. Code merged to `main` must be deployed manually. This spec defines a CI-gated continuous deployment pipeline that automatically deploys both the FastAPI backend and Next.js frontend to Vercel on every merge to `main`, but only after all CI checks pass.

---

## 2. Scope

### In scope
- GitHub Actions `deploy` job added to existing `ci.yml`, triggered after `ci` job passes on `main`
- FastAPI backend deployed to Vercel as a Python serverless function (`dke/` project root)
- Next.js frontend deployed to Vercel (`frontend/` project root)
- `gap_analysis_worker` asyncio lifespan task replaced with a Vercel Cron Job (1-minute interval)
- `CRON_SECRET` env var authenticates Vercel → cron endpoint calls
- Vercel native Git integration disabled on both projects (GitHub Actions is sole deploy trigger)

### Out of scope
- Preview deployments on PRs
- Rollback automation
- Deployment notifications (Slack, email)
- Multi-environment staging setup

---

## 3. Architecture

```
merge PR → main
      ↓
GitHub Actions: ci job (existing)
  ├─ Gitleaks secrets scan
  ├─ Ruff lint, Mypy, Bandit, pip-audit, Pytest
  └─ ESLint, tsc --noEmit, npm audit, Next.js build
      ↓ all pass
GitHub Actions: deploy job (new — only on main push)
  ├─ vercel deploy --prod  (backend: dke/)
  └─ vercel deploy --prod  (frontend: frontend/)
      ↓
Vercel: two projects
  ├─ dke-backend   (Python/FastAPI, root: dke/)
  │     └─ Cron: GET /gaps/analyze/cron  every minute
  └─ dke-frontend  (Next.js 15, root: frontend/)
```

**Key invariants:**
- PRs: `ci` job only — no deployment
- Merge to `main`: `ci` must pass before `deploy` runs; if `ci` fails, deploy is skipped
- Vercel native Git integration is disabled — GitHub Actions is the sole deploy trigger

---

## 4. FastAPI on Vercel

### Project structure

Vercel's Python runtime requires an entry point at `api/index.py` relative to the project root (`dke/`). A thin adapter file re-exports the existing FastAPI app — no changes to `backend/`.

```
dke/
├── api/
│   └── index.py          ← NEW: Vercel entry point
├── backend/
│   └── api/
│       └── main.py       ← existing app (lifespan worker removed)
├── requirements.txt
└── vercel.json           ← NEW: cron config
```

**`dke/api/index.py`:**
```python
from backend.api.main import app  # noqa: F401
```

**`dke/vercel.json`:**
```json
{
  "crons": [
    {
      "path": "/gaps/analyze/cron",
      "schedule": "* * * * *"
    }
  ]
}
```

---

## 5. Gap Analysis Worker Migration

The `asyncio.create_task(gap_analysis_worker())` lifespan task is incompatible with Vercel's stateless serverless model. It is replaced by a Vercel Cron Job that fires every minute.

### Changes to `backend/api/main.py`

Remove from lifespan:
```python
# REMOVE these lines:
asyncio.create_task(gap_analysis_worker())
```

The lifespan context manager can be removed entirely if `gap_analysis_worker` was its only purpose.

### New cron endpoint

Added to `backend/api/routes/gaps.py`:

```python
@router.get("/gaps/analyze/cron")
async def gap_analysis_cron(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    auth = request.headers.get("authorization")
    if auth != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Insert job — no-op if one is already pending/running (unique partial index)
    result = await db.execute(text("""
        INSERT INTO gap_analysis_jobs (status)
        VALUES ('pending')
        ON CONFLICT DO NOTHING
        RETURNING id
    """))
    job_row = result.fetchone()
    if job_row is None:
        return {"ok": True, "skipped": "job already active"}

    await db.commit()
    await run_gap_analysis(db)
    return {"ok": True}
```

**Deduplication is unchanged.** The unique partial index on `gap_analysis_jobs (status) WHERE status IN ('pending', 'running')` still prevents concurrent runs — if the previous cron invocation is still running when the next fires, `INSERT ... ON CONFLICT DO NOTHING` returns no rows and the new invocation exits immediately.

Vercel Functions default to 300s timeout — sufficient for gap analysis execution.

### New config field

Add to `backend/config.py`:
```python
cron_secret: str = ""
```

---

## 6. GitHub Actions Workflow

The existing `ci.yml` gains a `deploy` job. The `ci` job is unchanged.

```yaml
name: CI/CD

on:
  pull_request:
  push:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      # ... all existing steps unchanged ...

  deploy:
    needs: ci
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deploy backend to Vercel
        run: npx vercel deploy --prod --yes --cwd dke
        env:
          VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_BACKEND_PROJECT_ID }}

      - name: Deploy frontend to Vercel
        run: npx vercel deploy --prod --yes --cwd frontend
        env:
          VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_FRONTEND_PROJECT_ID }}
```

---

## 7. Secrets & Environment Variables

### GitHub Secrets (repository settings)

| Secret | Where to get it |
|---|---|
| `VERCEL_TOKEN` | Vercel dashboard → Account Settings → Tokens |
| `VERCEL_ORG_ID` | `.vercel/project.json` after `vercel link` |
| `VERCEL_BACKEND_PROJECT_ID` | `.vercel/project.json` in `dke/` after `vercel link` |
| `VERCEL_FRONTEND_PROJECT_ID` | `.vercel/project.json` in `frontend/` after `vercel link` |

### Vercel Environment Variables — Backend project

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `GROQ_API_KEY` | Groq API key |
| `CRON_SECRET` | Random secret string (generate with `openssl rand -hex 32`) |
| `FRONTEND_URL` | `https://your-dke-frontend.vercel.app` |
| `GAP_ANALYSIS_THRESHOLD` | `10` |

### Vercel Environment Variables — Frontend project

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://your-dke-backend.vercel.app` |
| `NEXT_PUBLIC_APP_URL` | `https://your-dke-frontend.vercel.app` |

---

## 8. One-Time Setup Steps

These steps are performed once before the first automated deployment.

1. **Link Vercel projects:**
   ```bash
   cd dke && vercel link      # creates dke-backend project
   cd frontend && vercel link  # creates dke-frontend project
   ```

2. **Disable Vercel native Git integration** on both projects:
   Dashboard → Project Settings → Git → disconnect repository

3. **Set environment variables** in Vercel dashboard for each project (see Section 7)

4. **Add GitHub Secrets** in repository Settings → Secrets and variables → Actions (see Section 7)

---

## 9. Files Changed

| File | Type | Purpose |
|---|---|---|
| `.github/workflows/ci.yml` | Modified | Add `deploy` job after `ci` |
| `dke/api/index.py` | New | Vercel Python entry point |
| `dke/vercel.json` | New | Cron schedule config |
| `dke/backend/api/main.py` | Modified | Remove `gap_analysis_worker` lifespan task |
| `dke/backend/api/routes/gaps.py` | Modified | Add `GET /gaps/analyze/cron` endpoint |
| `dke/backend/config.py` | Modified | Add `cron_secret` field |

---

## 10. Verification Checklist

1. Open a PR → verify only the `ci` job runs, no deployment
2. Merge PR to `main` with all checks passing → verify `deploy` job runs and both projects show new deployment in Vercel dashboard
3. Merge a PR that breaks Ruff lint → verify `ci` fails and `deploy` job is skipped
4. Wait 1 minute after backend deploys → verify Vercel Cron fires `GET /gaps/analyze/cron` (visible in Vercel Functions logs)
5. Hit `GET /gaps/analyze/cron` directly without `Authorization` header → verify 401 response
6. Trigger two rapid cron calls → verify second returns `{"skipped": "job already active"}` (deduplication works)
7. Verify `gap_analysis_jobs` table row transitions `pending → running → done` after cron fires
