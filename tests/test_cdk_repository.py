import sqlite3

import pytest

from app.db import create_connection, initialize_database
from app.repositories import CdkRepository


@pytest.fixture()
def connection():
    conn = create_connection(":memory:")
    initialize_database(conn)
    yield conn
    conn.close()


def test_generate_batch_creates_unique_available_cdks(connection):
    repo = CdkRepository(connection)

    codes = repo.generate_batch(count=5, batch_name="首批")

    assert len(codes) == 5
    assert len(set(codes)) == 5
    rows = connection.execute("select code, status, batch_name from cdks").fetchall()
    assert {row["status"] for row in rows} == {"available"}
    assert {row["batch_name"] for row in rows} == {"首批"}


def test_mark_used_rejects_reusing_same_cdk(connection):
    repo = CdkRepository(connection)
    [code] = repo.generate_batch(count=1, batch_name="单测")

    cdk = repo.get_available_by_code(code)
    repo.mark_used(cdk["id"], order_id=42)

    assert repo.get_available_by_code(code) is None
    with pytest.raises(sqlite3.IntegrityError):
        repo.mark_used(cdk["id"], order_id=43)
