from typing import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import backend.models  # noqa: F401 — registers all models with Base
from backend.db.postgres import Base

TEST_DATABASE_URL = "postgresql+asyncpg://neondb_owner:npg_cG5dHlVRBZ4m@ep-quiet-wildflower-an81ckms-pooler.c-6.us-east-1.aws.neon.tech/dke_test"


@pytest.fixture(scope="function")
async def test_engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
