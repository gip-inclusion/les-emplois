from django import forms
from django.urls import reverse_lazy
from django.utils.datastructures import MultiValueDict

from itou.cities.models import City
from itou.siaes.models import Siae
from itou.utils.address.departments import DEPARTMENTS, DEPARTMENTS_WITH_DISTRICTS


class SiaeSearchForm(forms.Form):

    DISTANCES = [10, 15, 25, 50, 75, 100]
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in DISTANCES]
    DISTANCE_DEFAULT = 25

    CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

    # We temporarily hide ACIPHC kind in search filter until our staff has input enough of them, per their request.
    KIND_CHOICES = [(k, f"{v} ({k})") for k, v in Siae.KIND_CHOICES if k != Siae.KIND_ACIPHC]

    distance = forms.ChoiceField(
        label="Distance",
        required=False,
        initial=DISTANCE_DEFAULT,
        choices=DISTANCE_CHOICES,
        widget=forms.RadioSelect,
    )

    # The hidden `city` field is populated by the autocomplete JavaScript mechanism,
    # see `city_autocomplete_field.js`.
    city = forms.CharField(widget=forms.HiddenInput(attrs={"class": "js-city-autocomplete-hidden"}))
    city_name = forms.CharField(
        label="Ville",
        required=False,
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

    kinds = forms.MultipleChoiceField(
        label="Types de structure",
        choices=KIND_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, data=None, **kwargs):
        initial = kwargs.get("initial", {})
        if data:
            # To render the default distance value as checked in radio widget
            data = MultiValueDict({**{k: [v] for k, v in initial.items()}, **data})
        super().__init__(data, **kwargs)

    def clean_distance(self):
        distance = self.cleaned_data["distance"]
        if not distance:
            distance = self.fields["distance"].initial
        return distance

    def clean_city(self):
        slug = self.cleaned_data["city"]
        try:
            return City.objects.get(slug=slug)
        except City.DoesNotExist as e:
            raise forms.ValidationError(f"La ville « {slug} » n'existe pas.") from e

    def add_field_departements(self, departments):
        # Build list of choices
        choices = ((department, DEPARTMENTS[department]) for department in departments)
        self.fields["departments"] = forms.ChoiceField(
            label="Départements",
            required=False,
            choices=choices,
            widget=forms.CheckboxSelectMultiple(),
        )

    def add_field_districts(self, department, districts):
        # Build list of choices
        def format_district(post_code):
            # Could use ordinal from humanize for would be overkill
            number = int(post_code) - (int(department) * 1000)
            return "1er" if number == 1 else f"{number}e"

        choices = ((district, format_district(district)) for district in districts)
        field_name = f"districts_{department}"
        self.fields[field_name] = forms.ChoiceField(
            label=f"Arrondissements de {DEPARTMENTS_WITH_DISTRICTS[department]['city']}",
            required=False,
            choices=choices,
            widget=forms.CheckboxSelectMultiple(),
        )


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
        except City.DoesNotExist as e:
            raise forms.ValidationError("La ville  « {slug} » n'existe pas.") from e
