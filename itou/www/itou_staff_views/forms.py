import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.utils import timezone

from itou.common_apps.address.departments import DEPARTMENTS
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
