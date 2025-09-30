import pytest
from django.db import connection

from itou.metabase.tables.utils import (
    get_ai_stock_job_seeker_pks,
    get_insee_code_to_zrr_status_map,
    get_post_code_to_insee_cities_map,
    get_qpv_job_seeker_pks,
)


@pytest.fixture(name="metabase")
def metabase_fixture(mocker):
    class FakePsycopgConnection:
        """
        This fake psycopg connection allows us to benefit from all
        the Django heavy lifting that is done with creating the database,
        wrap everything in a transaction, etc.

        This makes us write the metabase tables in the main test database.
        """

        def __enter__(self):
            return connection

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    mocker.patch("itou.metabase.db.get_connection", return_value=FakePsycopgConnection())


@pytest.fixture(autouse=True)
def clear_pks_caches():
    get_ai_stock_job_seeker_pks.cache_clear()
    get_insee_code_to_zrr_status_map.cache_clear()
    get_post_code_to_insee_cities_map.cache_clear()
    get_qpv_job_seeker_pks.cache_clear()
