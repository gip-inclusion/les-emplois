from django import forms
from django.urls import reverse_lazy

from itou.cities.models import City
from itou.siaes.models import Siae


class SiaeSearchForm(forms.Form):

    DISTANCES = [100, 75, 50, 25, 15, 10, 5]
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in DISTANCES]
    DISTANCE_DEFAULT = 5

    CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

    # We temporarily hide ACIPHC kind in search filter until our staff has input enough of them, per their request.
    KIND_CHOICES = [("", "---")] + [(k[0], k[0]) for k in Siae.KIND_CHOICES if k[0] != Siae.KIND_ACIPHC]

    distance = forms.ChoiceField(
        label="Distance",
        initial=DISTANCE_DEFAULT,
        choices=DISTANCE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control text-center custom-select"}),
    )

    # The hidden `city` field is populated by the autocomplete JavaScript mechanism,
    # see `city_autocomplete_field.js`.
    city = forms.CharField(widget=forms.HiddenInput(attrs={"class": "js-city-autocomplete-hidden"}))
    city_name = forms.CharField(
        label="Ville",
        widget=forms.TextInput(
            attrs={
                "class": "js-city-autocomplete-input form-control",
                "data-autocomplete-source-url": CITY_AUTOCOMPLETE_SOURCE_URL,
                "data-autosubmit-on-enter-pressed": 1,
                "placeholder": "Autour de (Arras, Bobigny, Strasbourg…)",
                "autocomplete": "off",
            }
        ),
    )

    kind = forms.ChoiceField(
        label="Type de structure",
        choices=KIND_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-control text-center custom-select"}),
    )

    def clean_city(self):
        slug = self.cleaned_data["city"]
        try:
            return City.objects.get(slug=slug)
        except City.DoesNotExist:
            raise forms.ValidationError("Cette ville n'existe pas.")


class PrescriberSearchForm(forms.Form):

    DISTANCES = [100, 75, 50, 25, 15, 10, 5]
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in DISTANCES]
    DISTANCE_DEFAULT = 5

    CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

    distance = forms.ChoiceField(
        label="Distance",
        initial=DISTANCE_DEFAULT,
        choices=DISTANCE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control text-center custom-select"}),
    )

    # The hidden `city` field is populated by the autocomplete JavaScript mechanism,
    # see `city_autocomplete_field.js`.
    city = forms.CharField(widget=forms.HiddenInput(attrs={"class": "js-city-autocomplete-hidden"}))
    city_name = forms.CharField(
        label="Ville",
        widget=forms.TextInput(
            attrs={
                "class": "js-city-autocomplete-input form-control",
                "data-autocomplete-source-url": CITY_AUTOCOMPLETE_SOURCE_URL,
                "data-autosubmit-on-enter-pressed": 1,
                "placeholder": "Autour de (Arras, Bobigny, Strasbourg…)",
                "autocomplete": "off",
            }
        ),
    )

    def clean_city(self):
        slug = self.cleaned_data["city"]
        try:
            return City.objects.get(slug=slug)
        except City.DoesNotExist:
            raise forms.ValidationError("Cette ville n'existe pas.")
