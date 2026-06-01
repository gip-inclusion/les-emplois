from django import forms
from django.urls import reverse_lazy

from itou.recommendations.enums import ProfileFlag
from itou.recommendations.models import Beneficiary
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class BeneficiaryListFilterForm(forms.Form):
    beneficiary = forms.ModelChoiceField(
        queryset=Beneficiary.objects.none(),  # overridden in __init__
        required=False,
        label="Nom du demandeur d'emploi",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--cache": "true",
                "data-ajax--delay": 250,
                "data-ajax--type": "GET",
                "data-minimum-input-length": 1,
                "data-placeholder": "Nom du demandeur d'emploi",
                "data-ajax--url": reverse_lazy("recommendations:beneficiary_autocomplete"),
            }
        ),
    )
    profile_kinds = forms.MultipleChoiceField(
        label="Type de profil",
        choices=ProfileFlag.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, beneficiaries_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["beneficiary"].widget.label_from_instance = lambda obj: obj.get_inverted_full_name()
        if beneficiaries_qs is not None:
            self.fields["beneficiary"].queryset = beneficiaries_qs


_AGE_CHOICES = [
    ("under_26", "Moins de 26 ans"),
    ("26_49", "26 – 49 ans"),
    ("50_and_more", "50 ans et plus"),
]

_ADDRESS_CHOICES = [
    ("city", "Même commune"),
    ("dept", "Même département"),
    ("region", "Même région"),
]

_EDUCATION_LEVEL_CHOICES = [
    ("below_v", "Inférieur au niveau V"),
    ("below_iii", "Inférieur au niveau III"),
]


class RecommendationsFilterForm(forms.Form):
    age = forms.MultipleChoiceField(
        label="Âge",
        choices=_AGE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    address = forms.MultipleChoiceField(
        label="Adresse",
        choices=_ADDRESS_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    criteria = forms.MultipleChoiceField(
        label="Critères de recommandation",
        choices=ProfileFlag.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    education_level = forms.MultipleChoiceField(
        label="Niveau d’études",
        choices=_EDUCATION_LEVEL_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    # FIXME lalba: à ajouter dans le HTML ?
    search = forms.CharField(
        label="Rechercher une action",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Rechercher une action"}),
    )
