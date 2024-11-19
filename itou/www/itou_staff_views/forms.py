import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.utils import timezone

from itou.common_apps.address.departments import DEPARTMENTS
from itou.users.models import User
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


class MergeUserForm(forms.Form):
    old_email = forms.EmailField(
        label="Ancien e-mail",
        help_text="Email du compte à conserver.",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    new_email = forms.EmailField(
        label="Nouvel e-mail",
        help_text="Email du compte dont on va migrer les relations, et les informations personnelles.",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def _check_email_exists(self, email):
        user = User.objects.filter(email=email).first()
        if not user:
            raise ValidationError("Cet utilisateur n'existe pas.")
        return user

    def clean_old_email(self):
        self.old_user = self._check_email_exists(self.cleaned_data["old_email"])

    def clean_new_email(self):
        self.new_user = self._check_email_exists(self.cleaned_data["new_email"])

    def clean(self):
        cleaned_data = super().clean()
        new_user = getattr(self, "new_user", None)
        old_user = getattr(self, "old_user", None)
        if old_user and new_user and old_user == new_user:
            raise ValidationError("Les deux adresses doivent être différentes.")
        return cleaned_data


class MergeUserConfirmForm(forms.Form):
    update_personal_data = forms.TypedChoiceField(
        coerce=lambda v: v == "True",
        choices=((False, "False"), (True, "True")),
    )
