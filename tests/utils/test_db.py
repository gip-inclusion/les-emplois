import pytest
from django.db import connection
from django.db.utils import OperationalError

from itou.utils.db import get_lock_id, pg_advisory_lock


class TestPgAdvisoryLock:
    def setup_method(self):
        params = connection.get_connection_params()
        self.other = connection.get_new_connection(params)

    def teardown_method(self):
        self.other.close()
        with connection.cursor() as cursor:
            # If a test failed with an operational error, we need to
            # rollback to avoid a "django.db.utils.InternalError:
            # current transaction is aborted, commands ignored until
            # end of transaction block".
            cursor.execute("ROLLBACK")
            cursor.execute("SELECT pg_advisory_unlock_all()")

    def other_session_can_acquire_lock(self, name):
        with self.other.cursor() as cursor:
            result = cursor.execute("SELECT pg_try_advisory_lock(%s)", (get_lock_id(name),))
            acquired = result.fetchone()[0]
            if acquired:
                # Release so that this function is a no-op.
                cursor.execute("SELECT pg_advisory_unlock(%s)", (get_lock_id(name),))
        return acquired

    def lock_from_other_session(self, name):
        with self.other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (get_lock_id(name),))

    def test_lock_is_held_in_context_manager_and_released_on_exit(self):
        lock = "lock"
        with pg_advisory_lock(lock):
            assert not self.other_session_can_acquire_lock(lock)
        assert self.other_session_can_acquire_lock(lock)

    def test_different_names_yield_different_locks(self):
        with pg_advisory_lock("lock"):
            assert self.other_session_can_acquire_lock("other-lock")

    def test_blocks_if_lock_is_held_elsewhere(self):
        lock = "lock"
        self.lock_from_other_session(lock)
        body_ran = False
        with connection.cursor() as cursor:
            # Let's fail quickly.
            cursor.execute("SET lock_timeout = '50ms'")
            with pytest.raises(
                OperationalError,
                match="canceling statement due to lock timeout",
            ):
                with pg_advisory_lock(lock):
                    body_ran = True
        assert not body_ran
