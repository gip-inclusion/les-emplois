from django import forms
from django.urls import reverse_lazy
from django.utils.text import format_lazy

from itou.users.models import User
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class GpsUserSearchForm(forms.Form):
    # NB we need to inherit from forms.Form if we want the attributes
    # to be added to the a Form using this mixin (django magic)

    user = forms.ModelChoiceField(
        queryset=User.objects,
        label="Nom et prénom du candidat",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": format_lazy("{}?select2=", reverse_lazy("autocomplete:gps_users")),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 2,
                "data-placeholder": "Jean DUPONT",
            },
        ),
        required=True,
    )

    is_referent = forms.BooleanField(label="Se rattacher comme référent", required=False)
