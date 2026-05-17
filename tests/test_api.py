import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from uuid import uuid4


@pytest.fixture
async def client():
    import backend.models  # noqa: F401
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_post_bookmark_returns_pending(client):
    with patch("backend.api.routes.bookmarks.process_bookmark", new=AsyncMock()):
        resp = await client.post("/bookmarks", json={"url": "https://example.com"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["url"] == "https://example.com"


async def test_post_bookmarks_bulk_returns_queued_count(client):
    with patch("backend.api.routes.bookmarks.process_bookmarks_bulk", new=AsyncMock()):
        resp = await client.post(
            "/bookmarks/bulk",
            json={"urls": ["https://a.com", "https://b.com", "https://c.com"]},
        )

    assert resp.status_code == 200
    assert resp.json()["queued"] == 3


async def test_get_bookmarks_returns_list(client):
    resp = await client.get("/bookmarks")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_bookmark_by_id_returns_404_for_unknown(client):
    resp = await client.get(f"/bookmarks/{uuid4()}")
    assert resp.status_code == 404
