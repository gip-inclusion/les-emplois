import pytest
from django.db import connection

from itou.metabase import dataframes, db
from itou.metabase.tables.utils import get_insee_code_to_zrr_status_map, get_qpv_job_seeker_pks


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

    monkeypatch.setattr(dataframes, "MetabaseDatabaseCursor", FakeMetabase)
    monkeypatch.setattr(db, "MetabaseDatabaseCursor", FakeMetabase)


@pytest.fixture(autouse=True)
def clear_qpv_cache():
    # Clear cache on get_qpv_job_seeker_pks to ensure we have the correct data
    # and that the query is always performed
    get_qpv_job_seeker_pks.cache_clear()


@pytest.fixture(autouse=True)
def clear_zrr_cache():
    # Clear cache on get_insee_code_to_zrr_status_map to ensure we have the correct data
    # and that the query is always performed
    get_insee_code_to_zrr_status_map.cache_clear()
