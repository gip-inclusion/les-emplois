from django.db import connection

from itou.utils import triggers


def fields_history(get_response):
    def middleware(request):
        with connection.execute_wrapper(triggers._set_context_connection_wrapper):
            return get_response(request)

    return middleware
