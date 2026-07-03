from base64 import b32encode

from django import forms
from django.utils.html import mark_safe

from itou.otp.utils import get_user_devices
from itou.www.otp_views.enums import DeviceType


class ConfirmTOTPDeviceForm(forms.Form):
    name = forms.CharField(
        label="Choisissez un nom pour votre appareil",
        help_text="Ce nom vous aidera à retrouver cet appareil dans vos paramètres de sécurité.",
    )
    otp_token = forms.CharField(label="")  # customized in `__init__()`
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
        self.fields["otp_token"].label = mark_safe(
            "Une fois le service ajouté, un code à 6 chiffres s'affiche automatiquement "
            + (
                "dans votre application."
                if device_type == DeviceType.SMARTPHONE
                else "dans votre gestionnaire de mots de passe."
            )
            + "<br>Reportez-le ici :"
        )

    def clean(self):
        cleaned_data = super().clean()

        if self.device.user.itou_totp_devices.filter(name=cleaned_data["name"], disabled_at=None).exists():
            self.add_error(
                "name", "Vous avez déjà enregistré un appareil sous le même nom. Veuillez choisir un nom différent."
            )

        if self.device.verify_token(cleaned_data["otp_token"]) is False:
            self.add_error("otp_token", "Le code unique de validation (OTP) n’est pas correct.")

        return cleaned_data


class LoginWithBackupCodeForm(forms.Form):
    code = forms.CharField(label="Entrez le code de récupération")

    def __init__(self, *args, static_device, **kwargs):
        super().__init__(*args, **kwargs)
        self.static_device = static_device

    def clean(self):
        cleaned_data = super().clean()

        code = cleaned_data["code"]
        if not self.static_device.verify_token(code):
            self.add_error("code", "Le code de récupération n’est pas correct.")

        return cleaned_data


class VerifyOTPForm(forms.Form):
    otp_token = forms.CharField(
        required=True,
        label="Entrez le code de validation unique (OTP)",
        help_text=(
            "Code à 6 chiffres généré par votre application mobile "
            "ou votre gestionnaire de mot de passe sur votre ordinateur"
        ),
    )

    otp_token.widget.attrs.update(
        {
            "max_length": 6,
            "autocomplete": "one-time-code",
            "autofocus": True,
        }
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_otp_token(self):
        otp_token = self.cleaned_data.get("otp_token")

        device = next(
            (d for d in get_user_devices(self.user) if d.verify_token(otp_token)),
            None,
        )
        if device is None:
            raise forms.ValidationError("Le code de validation unique (OTP) n’est pas correct.")
        self.user.otp_device = device

        return otp_token
