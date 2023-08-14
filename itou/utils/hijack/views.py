from hijack import views


HIJACK_KEY = "hijack_previous_url"


class AcquireUserView(views.AcquireUserView):
    def post(self, request, *args, **kwargs):
        previous_url = self.request.META.get("HTTP_REFERER")
        res = super().post(request, *args, **kwargs)
        if previous_url:
            self.request.session[HIJACK_KEY] = previous_url
        return res


class ReleaseUserView(views.ReleaseUserView):
    def post(self, request, *args, **kwargs):
        self.previous_url = self.request.session.get(HIJACK_KEY)
        return super().post(request, *args, **kwargs)

    def get_success_url(self):
        return self.previous_url or super().get_success_url()
