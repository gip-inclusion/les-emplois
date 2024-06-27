import pytest
from django.db import connection

from itou.metabase import dataframes, db
from itou.metabase.tables.utils import (
    get_active_companies_pks,
    get_ai_stock_job_seeker_pks,
    get_insee_code_to_zrr_status_map,
    get_post_code_to_insee_code_map,
    get_qpv_job_seeker_pks,
)


@pytest.fixture(name="metabase")
def metabase_fixture(monkeypatch, settings):
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

    def get_cursor(*args):
        return FakeMetabase()

    monkeypatch.setattr(dataframes, "get_cursor", get_cursor)
    monkeypatch.setattr(db, "get_cursor", get_cursor)
    # This setting need to be editable in `dev` to manually test transferring data from "les emplois" to "pilotage",
    # but the one used in `test` should be fixed, `dev` inheriting from `test` we can't put it in settings.
    monkeypatch.setattr(settings, "METABASE_HASH_SALT", None)


@pytest.fixture(autouse=True)
def clear_pks_caches():
    get_active_companies_pks.cache_clear()
    get_ai_stock_job_seeker_pks.cache_clear()
    get_insee_code_to_zrr_status_map.cache_clear()
    get_post_code_to_insee_code_map.cache_clear()
    get_qpv_job_seeker_pks.cache_clear()
