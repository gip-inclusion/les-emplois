import pytest
from django.db import connection


class ForceConnectedTransaction:
    """This context manager could come in handy in our long-standing workers,
    by calling it before an operation that could potentially be a little long.

    We get InterfaceError: "connection already closed" in some of our workers
    and by default, Django does not rconnect in such cases.

    This is a draft of a tool that would help us reconnect before any operation
    starts, even though it does not protect us from very random disconnections
    and does not retry failed operations. Is not there, somewhere, a special
    database conenctor that could do that ?
    """

    def __enter__(self):
        if not connection.is_usable():
            connection.connect()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        pass


@pytest.mark.usefixtures("metabase")
@pytest.mark.django_db()
def test_interface_error():
    connection.close()
    assert not connection.is_usable()

    with ForceConnectedTransaction():
        assert connection.is_usable()

    # unfortunately, if the assertions do pass, the test fails in an error (not a failure)
    # bacause pytest-django tries to tear down ad database that is in a weird state according
    # to it. I did not crack this issue just yet :/
