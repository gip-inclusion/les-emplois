from django import forms

from itou.directory.enums import ContactMethod
from itou.nexus.enums import NexusStructureKind


class PeopleSearchForm(forms.Form):
    q = forms.CharField(
        label="Rechercher une personne",
        required=False,
        widget=forms.TextInput(
            attrs={
                "id": "q-personnes",
                "placeholder": "Nom ou prénom",
                "autocomplete": "off",
                "class": "form-control",
            }
        ),
    )
    types = forms.MultipleChoiceField(
        label="Types de structure",
        choices=NexusStructureKind.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    contacts = forms.MultipleChoiceField(
        label="Moyens de contact",
        choices=ContactMethod.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
