from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def db() -> AsyncGenerator[AsyncMock, None]:
    """Mock database session — no live connection needed."""
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value.scalars.return_value.all.return_value = []
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.execute.return_value.scalar_one.return_value = MagicMock()
    yield session


@pytest.fixture(autouse=True)
def _override_get_db():
    """Override FastAPI's get_db dependency so API tests need no live DB."""
    from backend.api.main import app
    from backend.db.postgres import get_db

    async def _mock_get_db():
        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value.scalars.return_value.all.return_value = []
        session.execute.return_value.scalar_one_or_none.return_value = None
        yield session

    app.dependency_overrides[get_db] = _mock_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
