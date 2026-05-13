async def test_db_session_interface(db):
    """db fixture provides a usable session interface in tests."""
    assert db is not None
    db.add(object())
    await db.commit()
