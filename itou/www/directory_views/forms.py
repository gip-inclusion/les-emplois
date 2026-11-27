from django import forms
from django.forms import widgets

from itou.companies.enums import CompanyKind
from itou.prescribers.enums import PrescriberOrganizationKind


class PeopleSearchForm(forms.Form):
    q = forms.CharField(
        label="Rechercher une personne",
        required=False,
        widget=widgets.SearchInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "Rechercher une personne",
            }
        ),
    )
    kind = forms.MultipleChoiceField(
        label="Type de structure",
        choices=sorted(CompanyKind.choices + PrescriberOrganizationKind.choices),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
