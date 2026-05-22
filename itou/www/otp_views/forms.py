from base64 import b32encode

from django import forms

from itou.www.otp_views.enums import DeviceType


class ConfirmTOTPDeviceForm(forms.Form):
    name = forms.CharField(
        label="Choisissez un nom pour votre appareil",
        help_text="Ce nom vous aidera à retrouver cet appareil dans vos paramètres de sécurité.",
    )
    otp_token = forms.CharField(label="Générez le code unique de validation (OTP) dans l’application et entrez-le ici")
    key = forms.CharField(widget=forms.HiddenInput)
    device_type = forms.CharField(widget=forms.HiddenInput)

    otp_token.widget.attrs.update(
        {
            "max_length": 6,
            "autocomplete": "one-time-code",
        }
    )

    def __init__(self, *args, device_type, device, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = device
        self.fields["key"].initial = b32encode(device.bin_key).decode()
        self.fields["device_type"].initial = device_type
        self.fields["name"].widget.attrs.update(
            {"placeholder": "Téléphone pro" if device_type == DeviceType.SMARTPHONE else "Ordinateur pro"}
        )

    def clean(self):
        cleaned_data = super().clean()

        otp_token = cleaned_data["otp_token"]
        if self.device.verify_token(otp_token) is False:
            self.add_error("otp_token", "Le code unique de validation (OTP) n’est pas correct.")

        return cleaned_data
