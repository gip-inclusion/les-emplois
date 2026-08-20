from django import forms
from django.contrib.admin import widgets
from django.core.exceptions import ValidationError

from itou.companies.models import Company
from itou.utils.admin import ChooseFieldsToTransfer, FakeRelForRawIdWidget


class SelectTargetCompanyForm(forms.Form):
    to_company = forms.ModelChoiceField(Company.objects.all(), required=True, label="Choisissez l’entreprise cible")

    def __init__(self, *args, from_company, admin_site, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_company"].widget = widgets.ForeignKeyRawIdWidget(FakeRelForRawIdWidget(Company), admin_site)
        self.from_company = from_company

    def clean_to_company(self):
        to_company = self.cleaned_data["to_company"]
        if to_company.pk == self.from_company.pk:
            raise ValidationError("L’entreprise cible doit être différente de celle d’origine")
        return to_company


class CompanyChooseFieldsToTransfer(ChooseFieldsToTransfer):
    disable_from_company = forms.BooleanField(label="Désactiver l’entreprise source", required=False, initial=True)
