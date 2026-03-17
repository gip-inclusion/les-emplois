from django import forms


class ConfirmTOTPDeviceForm(forms.Form):
    name = forms.CharField(label="Nom de l'appareil")
    otp_token = forms.CharField()

    otp_token.widget.attrs.update({"max_length": 6, "autocomplete": "one-time-code"})

    def __init__(self, *args, device, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = device

    def clean(self):
        cleaned_data = super().clean()

        otp_token = cleaned_data["otp_token"]
        if self.device.verify_token(otp_token) is False:
            self.add_error("otp_token", "Mauvais code OTP")

        return cleaned_data
