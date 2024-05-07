from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.text import format_lazy

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class GpsUserSearchForm(forms.Form):
    # NB we need to inherit from forms.Form if we want the attributes
    # to be added to the a Form using this mixin (django magic)

    user = forms.ModelChoiceField(
        queryset=User.objects.filter(kind=UserKind.JOB_SEEKER),
        label="Nom et prénom du candidat",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": format_lazy("{}?select2=", reverse_lazy("autocomplete:gps_users")),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 2,
                "lang": "",  # Needed to override the noResults i18n translation in JS.
                "id": "js-search-user-input",
            },
        ),
        required=True,
    )

    is_referent = forms.BooleanField(label="Se rattacher comme référent", required=False)

    def clean(self):
        super().clean()

        user = self.cleaned_data["user"]

        if not user.is_job_seeker:
            raise ValidationError("Seul un candidat peut être ajouté à un groupe de suivi")
