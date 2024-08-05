from django import forms
from django.urls import reverse_lazy
from django.utils.datastructures import MultiValueDict
from django.utils.text import format_lazy
from django_select2.forms import Select2Widget

from itou.cities.models import City
from itou.common_apps.address.departments import (
    DEPARTMENTS,
    DEPARTMENTS_ADJACENCY,
    DEPARTMENTS_WITH_DISTRICTS,
    format_district,
)
from itou.companies.enums import CompanyKind, ContractNature, ContractType
from itou.jobs.models import ROME_DOMAINS
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class SiaeSearchForm(forms.Form):
    DISTANCES = [5, 10, 15, 25, 50, 75, 100]
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in DISTANCES]
    DISTANCE_DEFAULT = 25

    KIND_CHOICES = [(k, f"{k} - {v}") for k, v in CompanyKind.choices]

    distance = forms.ChoiceField(
        label="Distance",
        required=False,
        initial=DISTANCE_DEFAULT,
        choices=DISTANCE_CHOICES,
        widget=forms.RadioSelect,
    )

    city = forms.ModelChoiceField(
        queryset=City.objects,
        label="Ville",
        to_field_name="slug",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "class": "form-control",
                "data-ajax--url": format_lazy("{}?slug=", reverse_lazy("autocomplete:cities")),
                "data-minimum-input-length": 1,
                "data-placeholder": "Rechercher un emploi inclusif autour de…",
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

    def add_field_departements(self, city):
        departments = sorted([city.department, *DEPARTMENTS_ADJACENCY.get(city.department, ())])
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

    def add_field_company(self, companies):
        # Build list of choices
        self.fields["company"] = forms.ChoiceField(
            label="Nom de la structure",
            required=False,
            choices=sorted(companies, key=lambda item: item[1]),
            widget=Select2Widget(attrs={"data-placeholder": "Nom de la structure"}),
        )


class JobDescriptionSearchForm(SiaeSearchForm):
    CONTRACT_TYPE_CHOICES = sorted(
        [(k, v) for k, v in ContractType.choices if k not in (ContractType.OTHER, ContractType.BUSINESS_CREATION)],
        key=lambda d: d[1],
    ) + [
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

    distance = forms.ChoiceField(
        label="Distance",
        required=False,
        initial=DISTANCE_DEFAULT,
        choices=DISTANCE_CHOICES,
        widget=forms.RadioSelect,
    )

    city = forms.ModelChoiceField(
        queryset=City.objects,
        label="Ville",
        to_field_name="slug",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "class": "form-control",
                "data-ajax--url": format_lazy("{}?slug=", reverse_lazy("autocomplete:cities")),
                "data-minimum-input-length": 2,
                "data-placeholder": "Rechercher un prescripteur autour de…",
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
