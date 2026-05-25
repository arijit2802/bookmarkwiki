from contextlib import asynccontextmanager

import backend.models  # noqa: F401 — register models before init_db
from fastapi import FastAPI

from backend.db.postgres import init_db
from backend.api.routes import bookmarks, wiki


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="DKE Wiki Compiler", lifespan=lifespan)
app.include_router(bookmarks.router)
app.include_router(wiki.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
