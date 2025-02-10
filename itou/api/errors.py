import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback


logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    if response is None:
        logger.exception("API Error: %s", exc)
        set_rollback()
        response = Response(data={"detail": "Something went wrong, sorry. We've been notified."}, status=500)

    return response
