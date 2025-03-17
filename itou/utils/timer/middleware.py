from itou.utils.timer import infos


class RequestTimerMiddleware:
    def __init__(self, get_response=None):
        self.get_response = get_response

    def __call__(self, request):
        infos.reinit()
        response = self.get_response(request)
        return response
