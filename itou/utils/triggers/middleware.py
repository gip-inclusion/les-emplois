from itou.utils import triggers


def fields_history(get_response):
    def middleware(request):
        with triggers.connection_wrapper():
            return get_response(request)

    return middleware
