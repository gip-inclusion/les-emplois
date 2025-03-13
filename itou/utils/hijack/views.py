from django_otp import DEVICE_ID_SESSION_KEY
from hijack import views


HIJACK_PREVIOUS_URL_SESSION_KEY = "hijack_previous_url"
HIJACK_OTP_SESSION_KEY = "hijack_otp_device_id"


class AcquireUserView(views.AcquireUserView):
    def post(self, request, *args, **kwargs):
        previous_url = self.request.META.get("HTTP_REFERER")
        otp_device_persistent_id = self.request.session.get(DEVICE_ID_SESSION_KEY)
        res = super().post(request, *args, **kwargs)
        if previous_url:
            self.request.session[HIJACK_PREVIOUS_URL_SESSION_KEY] = previous_url
        if otp_device_persistent_id:
            self.request.session[HIJACK_OTP_SESSION_KEY] = otp_device_persistent_id
        return res


class ReleaseUserView(views.ReleaseUserView):
    def post(self, request, *args, **kwargs):
        self.previous_url = self.request.session.get(HIJACK_PREVIOUS_URL_SESSION_KEY)
        otp_device_persistent_id = self.request.session.get(HIJACK_OTP_SESSION_KEY)
        res = super().post(request, *args, **kwargs)
        if otp_device_persistent_id:
            self.request.session[DEVICE_ID_SESSION_KEY] = otp_device_persistent_id
        return res

    def get_success_url(self):
        return self.previous_url or super().get_success_url()
