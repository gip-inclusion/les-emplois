from collections import namedtuple

from django import forms
from django.contrib.admin import widgets
from django.core.exceptions import ValidationError

from itou.companies.models import Company
from itou.utils.admin import ChooseFieldsToTransfer


class CompanyAdminForm(forms.ModelForm):
    # Add a custom form field that is not part of the model in the admin.
    extra_field_refresh_geocoding = forms.BooleanField(
        label="Recalculer le geocoding",
        help_text=(
            "Si cette case est cochée, les coordonnées géographiques seront mises à "
            "jour si l'adresse est correctement renseignée."
        ),
        required=False,
    )

    class Meta:
        model = Company
        fields = "__all__"


FakeField = namedtuple("FakeField", ("name",))


class FakeRelForToCompanyRawIdWidget:
    model = Company
    limit_choices_to = {}

    def get_related_field(self):
        # This must return something that has the name of an existing field
        return FakeField("id")


class SelectTargetCompanyForm(forms.Form):
    to_company = forms.ModelChoiceField(Company.objects.all(), required=True, label="Choisissez l’entreprise cible")

    def __init__(self, *args, from_company, admin_site, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_company"].widget = widgets.ForeignKeyRawIdWidget(FakeRelForToCompanyRawIdWidget(), admin_site)
        self.from_company = from_company

    def clean_to_company(self):
        to_company = self.cleaned_data["to_company"]
        if to_company.pk == self.from_company.pk:
            raise ValidationError("L’entreprise cible doit être différente de celle d’origine")
        return to_company


class CompanyChooseFieldsToTransfer(ChooseFieldsToTransfer):
    disable_from_company = forms.BooleanField(label="Désactiver l’entreprise source", required=False, initial=True)

    def __init__(self, *args, fields_choices, siae_evaluations, **kwargs):
        super().__init__(*args, fields_choices=fields_choices, **kwargs)
        if siae_evaluations:
            self.fields["ignore_siae_evaluations"] = forms.BooleanField(
                label="Ignorer la présence d'un contrôle a posteriori.",
                required=True,
            )
