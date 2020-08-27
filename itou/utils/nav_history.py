"""
Helpers to keep a navigation history in session.

Useful to find the previous step of multi-step sections of the site where
many possible paths are possible.

The session must contain an `url_history` entry.
"""

from django.urls import reverse


def push_url_in_history(session_key):
    """
    A decorator with a `session_key` argument that populates the URL history.

    It must be used in each views of a multi-step process except the first one
    which must set an `url_history` entry in session, e.g.:

    request.session[session_key] = {
        "url_history": [reverse(f"{request.resolver_match.namespace}:{request.resolver_match.url_name}")],
    }
    """

    def decorated(view):
        def wrapped(request, *args, **kwargs):

            session_data = request.session[session_key]
            url_history = session_data["url_history"]

            current_url = reverse(f"{request.resolver_match.namespace}:{request.resolver_match.url_name}")
            if current_url not in url_history:
                # The user has gone forwards: the page was never visited.
                url_history.append(current_url)
            else:
                # Otherwise the user has gone backwards: a page that was already visited is visited again.
                # Clear all history after the current url.
                current_url_index = url_history.index(current_url)
                url_history = url_history[: current_url_index + 1]

            session_data["url_history"] = url_history

            return view(request, *args, **kwargs)

        return wrapped

    return decorated


def get_prev_url_from_history(request, session_key):
    """
    Find previous step's URL in the navigation history.
    """

    session_data = request.session[session_key]
    url_history = session_data["url_history"]

    current_url = reverse(f"{request.resolver_match.namespace}:{request.resolver_match.url_name}")

    current_url_index = url_history.index(current_url)
    return session_data["url_history"][current_url_index - 1]
