import pytest
from huey.contrib.djhuey import HUEY


def test_xdist_workers_do_not_share_redis_queue(worker_id):
    """Tests counting or flushing enqueued tasks must not be disturbed by the ones running on other workers."""
    if worker_id in ("master", None):
        pytest.skip("Only relevant with pytest-xdist")
    # Immediate mode replaces HUEY.storage with an in-memory storage, whose queue key ignores the settings
    # Build the Redis storage that tests leaving immediate mode would use
    redis_storage = HUEY.get_storage(**HUEY.storage_kwargs)
    assert redis_storage.queue_key.endswith(worker_id)
