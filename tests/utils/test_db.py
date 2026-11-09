from unittest import mock

import pytest
from django.db import connection
from django.db.utils import OperationalError

from itou.utils.db import CannotAcquireLock, get_lock_id, pg_advisory_lock, pg_try_advisory_lock


class AdvisoryLockTestBase:
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


class TestPgAdvisoryLock(AdvisoryLockTestBase):
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


class TestPgTryAdvisoryLock(AdvisoryLockTestBase):
    def test_can_acquire_lock_if_not_already_held(self):
        self.lock_from_other_session("other-lock")
        lock = "lock"
        pg_try_advisory_lock(lock)
        assert not self.other_session_can_acquire_lock(lock)

        # release manually
        with connection.cursor() as cursor:
            cursor.execute("select pg_advisory_unlock(%s)", (get_lock_id(lock),))
        assert self.other_session_can_acquire_lock(lock)

    def test_cannot_acquire_lock_if_already_help(self):
        lock = "lock"
        self.lock_from_other_session(lock)
        with pytest.raises(CannotAcquireLock):
            pg_try_advisory_lock(lock)

    @pytest.mark.parametrize("conn_max_age", [10, None])
    def test_cannot_call_with_persistent_connections(self, conn_max_age):
        lock = "lock"
        with mock.patch.dict(
            connection.settings_dict,
            {"CONN_MAX_AGE": conn_max_age},
        ):
            with pytest.raises(
                ValueError,
                match="Cannot use `pg_try_advisory_lock.*",
            ):
                pg_try_advisory_lock(lock)
        # No lock has been acquired, another session can lock.
        assert self.other_session_can_acquire_lock(lock)
