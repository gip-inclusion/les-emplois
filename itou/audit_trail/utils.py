import contextlib

from django.contrib.auth import user_logged_in

from itou.audit_trail.receivers import on_user_logged_in


@contextlib.contextmanager
def inhibit_user_logged_in_signal():
    was_connected = user_logged_in.disconnect(on_user_logged_in)
    try:
        yield
    finally:
        if was_connected:
            user_logged_in.connect(on_user_logged_in)
