from django import forms
from django.urls import reverse

from itou.asp.models import Commune, Country
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


def formfield_for_birth_place(**kwargs):
    france = Country.objects.get(code=Country._CODE_FRANCE)
    return forms.ModelChoiceField(
        queryset=Commune.objects,
        label="Commune de naissance",
        help_text=(
            "La commune de naissance est obligatoire lorsque le salarié est né en France. "
            "Elle ne doit pas être renseignée s’il est né à l'étranger."
        ),
        required=False,
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": reverse("autocomplete:communes"),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 1,
                "data-placeholder": "Nom de la commune",
                "data-disable-target": "#id_birth_country",
                "data-target-value": f"{france.pk}",
            },
        ),
        **kwargs,
    )


def formfield_for_birth_country(**kwargs):
    france = Country.objects.get(code=Country._CODE_FRANCE)
    return forms.ModelChoiceField(
        Country.objects,
        label="Pays de naissance",
        required=False,
        widget=forms.Select(
            attrs={
                "data-disable-target": "#id_birth_place",
                "data-disable-target-unless-value": f"{france.pk}",
            },
        ),
    )
