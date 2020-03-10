from django import forms
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from itou.cities.models import City
from itou.siaes.models import Siae


class SiaeSearchForm(forms.Form):

    DISTANCES = [100, 75, 50, 25, 15, 10, 5]
    DISTANCE_CHOICES = [(i, gettext_lazy(f"{i} Km")) for i in DISTANCES]

    CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

    KIND_CHOICES = [("", "---")] + [(k[0], k[0]) for k in Siae.KIND_CHOICES]

    distance = forms.ChoiceField(
        choices=DISTANCE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control text-center custom-select"}),
    )

    # The hidden `city` field is populated by the autocomplete JavaScript mechanism,
    # see `city_autocomplete_field.js`.
    city = forms.CharField(
        widget=forms.HiddenInput(attrs={"class": "js-city-autocomplete-hidden"})
    )
    city_name = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "class": "js-city-autocomplete-input form-control",
                "data-autocomplete-source-url": CITY_AUTOCOMPLETE_SOURCE_URL,
                "placeholder": gettext_lazy("Autour de (Arras, Bobigny, Strasbourg…)"),
                "autocomplete": "off",
            }
        )
    )

    kind = forms.ChoiceField(
        choices=KIND_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-control text-center custom-select"}),
    )

    def clean_city(self):
        slug = self.cleaned_data["city"]
        try:
            return City.active_objects.get(slug=slug)
        except City.DoesNotExist:
            raise forms.ValidationError(_("Cette ville n'existe pas."))
