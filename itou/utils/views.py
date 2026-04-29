from functools import wraps

from itou.utils import triggers


def with_triggers_context(function=None, *, methods=None):
    if methods is None:
        methods = ["POST"]

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return view_func(request, *args, **kwargs)

            base_context = {
                "user": request.user.pk if request.user.is_authenticated else None,
                "request_id": request.request_id if hasattr(request, "request_id") else None,
            }

            with triggers.context(**base_context):
                return view_func(request, *args, **kwargs)

        return wrapper

    if function:
        return decorator(function)
    return decorator
