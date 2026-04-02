from itou.utils import triggers


def fields_history(get_response):
    def middleware(request):
        ro_request = getattr(request, "_readonly", None)
        if (ro_request is None and request.method in ["GET", "HEAD"]) or ro_request:
            return get_response(request)

        base_context = {
            "user": request.user.pk if request.user.is_authenticated else None,
            "request_id": request.request_id if hasattr(request, "request_id") else None,
        }
        with triggers.context(**base_context):
            return get_response(request)

    return middleware
