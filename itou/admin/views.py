from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.views.generic import FormView
from django_otp import login as otp_login, match_token


class ConfirmOTPForm(forms.Form):
    otp_token = forms.CharField(required=True)

    def clean_otp_token(self):
        otp_token = self.cleaned_data.get("otp_token")

        device = match_token(self.user, otp_token)
        if device is None:
            raise ValidationError("code invalide")
        self.user.otp_device = device

        return otp_token

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user


class AdminConfirmOTPAuthView(FormView):
    template_name = "admin/confirm_otp.html"
    success_url = reverse_lazy("admin:index")
    form_class = ConfirmOTPForm

    def get_form_kwargs(self):
        return super().get_form_kwargs() | {"user": self.request.user}

    def form_valid(self, form):
        otp_login(self.request, self.request.user.otp_device)
        return super().form_valid(form)
