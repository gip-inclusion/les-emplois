from itou.utils import triggers


def fields_history(get_response):
    def middleware(request):
        if request.method in ["GET", "HEAD"]:
            return get_response(request)

        base_context = {
            "user": request.user.pk if request.user.is_authenticated else None,
            "request_id": request.request_id if hasattr(request, "request_id") else None,
        }
        with triggers.context(**base_context):
            return get_response(request)

    return middleware
