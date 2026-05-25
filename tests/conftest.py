from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def _make_mock_result(scalar=None, scalars_list=None):
    """Return a MagicMock mimicking SQLAlchemy Result with sync methods."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalar_one.return_value = scalar or MagicMock()
    result.scalars.return_value.all.return_value = scalars_list if scalars_list is not None else []
    return result


@pytest.fixture
async def db() -> AsyncGenerator[AsyncMock, None]:
    """Mock database session — no live connection needed."""
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = _make_mock_result()
    yield session


@pytest.fixture(autouse=True)
def _override_get_db():
    """Override FastAPI's get_db dependency so API tests need no live DB."""
    from backend.api.main import app
    from backend.db.postgres import get_db

    async def _mock_get_db():
        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value = _make_mock_result()
        yield session

    app.dependency_overrides[get_db] = _mock_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
