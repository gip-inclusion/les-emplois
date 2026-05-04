import logging
from functools import wraps

from django.conf import settings
from django.db import connection, transaction
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods

from itou.utils.enums import ItouEnvironment


logger = logging.getLogger(__name__)


def only_readonly_allowed(execute, sql, params, many, context):
    if not sql.upper().startswith(("SELECT", "SAVEPOINT ", "RELEASE SAVEPOINT ")):
        error_msg = "Only SAVEPOINT/SELECT/RELEASE SAVEPOINT statements allowed in readonly views"
        if settings.ITOU_ENVIRONMENT in [ItouEnvironment.DEV, ItouEnvironment.TEST]:
            raise RuntimeError(error_msg)
        else:
            logger.error(error_msg)  # Notify issue to sentry
    return execute(sql, params, many, context)


def http_methods(function=None, *, db_readonly=frozenset(), db_write=frozenset(), auto_options=True):
    def decorator(view_func):
        allowed_methods = {"OPTIONS"} if auto_options else set()
        allowed_methods.update(db_readonly)
        allowed_methods.update(db_write)

        @require_http_methods(sorted(allowed_methods))
        @transaction.non_atomic_requests  # Let the wrapper decide if it needs a transaction
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method == "OPTIONS" and auto_options:
                response = HttpResponse()
                response.headers["Allow"] = ", ".join(sorted(allowed_methods))
                response.headers["Content-Length"] = "0"
                return response

            if request.method in db_write:
                # The request is not readonly: a transaction is needed
                with transaction.atomic():
                    return view_func(request, *args, **kwargs)
            # Here request.method is in db_readonly, thanks to require_http_methods decorator
            # No need for DB transaction since we're only reading
            # and the transaction isolation level is READ COMMITED
            with connection.execute_wrapper(only_readonly_allowed):
                return view_func(request, *args, **kwargs)

        # Add some attributes for view introspection
        wrapper._db_readonly = db_readonly
        wrapper._db_write = db_write
        return wrapper

    if function:
        return decorator(function)
    return decorator


readonly_view = http_methods(db_readonly=["GET", "HEAD"], db_write=[])


class ReadonlyViewMixin:
    @classmethod
    def as_view(cls, *args, **kwargs):
        view = super().as_view(*args, **kwargs)
        db_write = getattr(cls, "non_readonly_http_method_names", [])
        db_readonly = [method.upper() for method in cls.http_method_names if method.upper() not in db_write]
        # Let Django's View.options method handle response
        return http_methods(db_readonly=db_readonly, db_write=db_write, auto_options=False)(view)


class ReadonlyTemplateRenderingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_template_response(self, request, response):
        # Wrap render() method in a context manager to ensure we only perform readonly SQL queries
        # since the template late rendering happens outside any transaction
        response.render = connection.execute_wrapper(only_readonly_allowed)(response.render)
        return response
