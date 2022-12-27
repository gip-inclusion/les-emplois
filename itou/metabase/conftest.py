import pytest
from django.db import connection

from itou.metabase import db


@pytest.fixture(name="metabase")
def metabase_fixture(monkeypatch):
    class FakeMetabase:
        """
        This fake metabase database allows us to benefit from all
        the Django heavy lifting that is done with creating the database,
        wrap everything in a transaction, etc.

        This makes us write the metabase tables in the main test database.

        FIXME(vperron): This is very basic for now. It still does not handle
        initial table creation, there might be table name collision or other
        issues. Let's fix them as they arise.
        """

        def __init__(self):
            self.cursor = None

        def __enter__(self):
            self.cursor = connection.cursor().cursor
            return self.cursor, connection

        def __exit__(self, exc_type, exc_value, exc_traceback):
            if self.cursor:
                self.cursor.close()

    monkeypatch.setattr(db, "MetabaseDatabaseCursor", FakeMetabase)
