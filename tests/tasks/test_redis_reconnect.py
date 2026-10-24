import socket
from copy import copy

import pytest
from huey.contrib.djhuey import HUEY


@pytest.mark.parametrize("fails_after", [1, 2])
def test_redis_reconnect(fails_after, caplog, mocker):
    """This ensure that redis silently reconnects on read error.

    The retry config looks like:

        "retry": Retry(ExponentialBackoff(), 2),

    Without the retry we're getting a:

        redis.exception.ConnectionError: Connection closed by server

    from redis._parser.hiredis.read_from_socket, with Retry() it
    silently retries and works.
    """

    test_key = test_value = "test_redis_reconnect"
    reliable_recv_into = socket.socket.recv_into

    def unreliable_recv_into(self, buffer, nbytes=0, flags=0):
        """This mimic a connection lost, but beware: the redis server
        is not really down and had received and executed the command,
        we just hide the response. So don't use with command that
        alters the server state.
        """
        nonlocal fails_after
        fails_after -= 1
        if fails_after == 0:
            reliable_recv_into(self, copy(buffer), nbytes, flags)
            return 0
        return reliable_recv_into(self, buffer, nbytes, flags)

    HUEY.put(test_key, test_value)

    mocker.patch("socket.socket.recv_into", unreliable_recv_into)
    for _ in range(3):
        assert HUEY.get(test_key, peek=True) == test_value

    HUEY.delete(test_key)
