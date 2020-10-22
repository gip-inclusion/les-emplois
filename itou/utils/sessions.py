from django.contrib.sessions.models import Session


# Helper functions, session related


def kill_sessions_for_user(user_pk):
    """
    Synchronously delete all active sessions owned by user.
    The user is identified in the session by the `_auth_user_id` key.
    Excellent candidate for async processing.
    """
    assert user_pk

    sessions_to_kill = []

    # If any better solution, I buy it...
    for session in Session.objects.all():
        if session.get_decoded().get("_auth_user_id") == str(user_pk):
            sessions_to_kill.append(session)
    Session.objects.filter(pk__in=sessions_to_kill).delete()
