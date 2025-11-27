import datetime
import re

import pandas
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.utils import timezone

from itou.common_apps.address.departments import DEPARTMENTS
from itou.files.forms import ItouFileField
from itou.users.models import User
from itou.utils.constants import MB
from itou.utils.validators import validate_siret
from itou.utils.widgets import DuetDatePickerWidget


DEPARTMENTS_CHOICES = {
    code: label
    for code, label in DEPARTMENTS.items()
    # The department number does not always match the post code for these regions.
    # Don’t offer them for export.
    if not code.startswith(("2A", "2B", "97", "98"))
}


class ItouStaffExportJobApplicationForm(forms.Form):
    date_joined_from = forms.DateField(label="Comptes créés depuis le")
    date_joined_to = forms.DateField(label="Comptes créés jusqu’au")
    departments = forms.MultipleChoiceField(
        label="Départements",
        choices=DEPARTMENTS_CHOICES,
        initial=["44", "63", "78"],
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        max_date = timezone.localdate() - datetime.timedelta(days=1)
        for fieldname in ["date_joined_from", "date_joined_to"]:
            field = self.fields[fieldname]
            field.validators = [MaxValueValidator(max_date)]
            field.widget = DuetDatePickerWidget(attrs={"max": max_date.isoformat(), "placeholder": False})

    def clean(self):
        cleaned_data = super().clean()
        if not self.errors:
            if cleaned_data["date_joined_to"] < cleaned_data["date_joined_from"]:
                raise ValidationError(
                    "L’intervalle de date de création de compte est invalide, la fin est avant le début."
                )
        return cleaned_data


class ImportACIConvergencePHCForm(forms.Form):
    file = ItouFileField(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        max_upload_size=1 * MB,
        label="Fichier ACI Convergence PHC",
    )

    def clean(self):
        if not self.errors:
            file = self.cleaned_data["file"]
            siret_column = "SIRET"
            siret_replace_re = re.compile(r"[^0-9]*")
            df = pandas.read_excel(
                file,
                converters={siret_column: lambda siret: siret_replace_re.sub("", siret)},
                sheet_name=None,
                usecols=[siret_column],
            )
            document_sirets = set()
            for sheet_name, columns in df.items():
                try:
                    sirets = columns["SIRET"]
                except KeyError:
                    self.add_error("__all__", f"La feuille de calcul « {sheet_name} » n’a pas de colonne SIRET.")
                    continue
                for row_index, siret in enumerate(sirets, 2):
                    try:
                        validate_siret(siret)
                    except ValidationError as e:
                        self.add_error("__all__", f"Feuille « {sheet_name} », ligne {row_index} : {e.message}")
                    else:
                        document_sirets.add(siret)
            return {"document_sirets": document_sirets}
        return self.cleaned_data


class MergeUserForm(forms.Form):
    email_1 = forms.EmailField(
        label="E-mail du premier compte",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    email_2 = forms.EmailField(
        label="E-mail du second compte",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def _check_email_exists(self, email):
        user = User.objects.filter(email=email).first()
        if not user:
            raise ValidationError("Cet utilisateur n'existe pas.")
        return user

    def clean_email_1(self):
        self.user_1 = self._check_email_exists(self.cleaned_data["email_1"])

    def clean_email_2(self):
        self.user_2 = self._check_email_exists(self.cleaned_data["email_2"])

    def clean(self):
        cleaned_data = super().clean()
        user_1 = getattr(self, "user_1", None)
        user_2 = getattr(self, "user_2", None)
        if user_2 and user_1 and user_2 == user_1:
            raise ValidationError("Les deux adresses doivent être différentes.")
        return cleaned_data


class MergeUserConfirmForm(forms.Form):
    user_to_keep = forms.ChoiceField(
        choices=(("to_user", "to_user"), ("from_user", "from_user")),
    )

    def clean(self) -> None:
        cleaned_data = super().clean()
        if self.errors:
            self.add_error(None, "Vous devez choisir l'identité à conserver")
        return cleaned_data


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
