from functools import wraps

from django.db import connection, transaction


def only_select_allowed(execute, sql, params, many, context):
    if not sql.upper().startswith("SELECT"):
        raise Exception("Only SELECT statements allowed in readonly views")
    return execute(sql, params, many, context)


def readonly_view(function=None, *, except_methods=None):
    def decorator(view_func):
        @transaction.non_atomic_requests  # Let the wrapper decide if it needs a transaction
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if except_methods and request.method in except_methods:
                request._readonly = False
                # The request is not readonly: a transaction is needed
                with transaction.atomic():
                    return view_func(request, *args, **kwargs)
            # No need for DB transaction since we're only reading
            # and the transaction isolation level is READ COMMITED
            request._readonly = True
            with connection.execute_wrapper(only_select_allowed):
                return view_func(request, *args, **kwargs)

        return wrapper

    if function:
        return decorator(function)
    return decorator


class ReadonlyViewMixin:
    @classmethod
    def as_view(cls, **initkwargs):
        view = super().as_view(**initkwargs)
        return readonly_view(except_methods=getattr(cls, "non_readonly_methods", None))(view)
