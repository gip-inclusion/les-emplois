from django import forms
from django.urls import reverse_lazy
from django.utils.datastructures import MultiValueDict

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, DEPARTMENTS_WITH_DISTRICTS, format_district
from itou.companies.enums import ContractNature, ContractType, SiaeKind
from itou.jobs.models import ROME_DOMAINS


class SiaeSearchForm(forms.Form):
    DISTANCES = [5, 10, 15, 25, 50, 75, 100]
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in DISTANCES]
    DISTANCE_DEFAULT = 25

    CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

    KIND_CHOICES = [(k, f"{k} - {v}") for k, v in SiaeKind.choices]

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

    def __init__(self, data: MultiValueDict = None, **kwargs):
        initial = kwargs.get("initial", {})
        if data:
            # Use the initial values as default values and extend them with the user data.
            # Useful to render the default distance values as checked in radio widgets.
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
        choices = ((district, format_district(district, department)) for district in districts)
        field_name = f"districts_{department}"
        self.fields[field_name] = forms.ChoiceField(
            label=f"Arrondissements de {DEPARTMENTS_WITH_DISTRICTS[department]['city']}",
            required=False,
            choices=choices,
            widget=forms.CheckboxSelectMultiple(),
        )


class JobDescriptionSearchForm(SiaeSearchForm):
    CONTRACT_TYPE_CHOICES = sorted(
        [(k, v) for k, v in ContractType.choices if k not in (ContractType.OTHER, ContractType.BUSINESS_CREATION)],
        key=lambda d: d[1],
    ) + [
        # FIXME(vperron): note that JS is used to add a "Nouveau" badge next to this entry until March 2023
        (ContractNature.PEC_OFFER, ContractNature.PEC_OFFER.label),
        (ContractType.BUSINESS_CREATION, ContractType.BUSINESS_CREATION.label),
        (ContractType.OTHER, ContractType.OTHER.label),
        ("", "Contrat non précisé"),
    ]

    contract_types = forms.MultipleChoiceField(
        label="Types de contrats",
        choices=CONTRACT_TYPE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    domains = forms.MultipleChoiceField(
        label="Domaines métier",
        choices=list(ROME_DOMAINS.items()),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )


class PrescriberSearchForm(forms.Form):
    DISTANCES = [5, 10, 15, 25, 50, 75, 100]
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in DISTANCES]
    DISTANCE_DEFAULT = 5

    CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

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
                "placeholder": "Autour de (Arras, Bobigny, Strasbourg…)",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(self, data: MultiValueDict = None, **kwargs):
        initial = kwargs.get("initial", {})
        if data:
            # Use the initial values as default values and extend them with the user data.
            # Useful to render the default distance values as checked in radio widgets.
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
            raise forms.ValidationError("La ville  « {slug} » n'existe pas.") from e
