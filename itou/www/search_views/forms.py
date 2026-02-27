from data_inclusion.schema import v1 as data_inclusion_v1
from django import forms
from django.http import QueryDict
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
from itou.companies.enums import CompanyKind, ContractType, JobSourceTag
from itou.jobs.models import ROME_DOMAINS
from itou.search.models import MAX_SAVED_SEARCHES_COUNT, SavedSearch
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class SiaeSearchForm(forms.Form):
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in [2, 5, 10, 15, 25, 50, 100]]
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
                "data-ajax--delay": 250,
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
        (JobSourceTag.FT_PEC_OFFER, JobSourceTag.FT_PEC_OFFER.label),
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
    DISTANCE_CHOICES = [(i, (f"{i} km")) for i in [2, 5, 10, 15, 25, 50, 100]]
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


class ServiceSearchForm(forms.Form):
    RECEPTION_ALL = "tous"

    city = forms.ModelChoiceField(
        queryset=City.objects,
        label="Ville",
        to_field_name="slug",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "class": "form-control",
                "data-ajax--url": format_lazy("{}?slug=", reverse_lazy("autocomplete:cities")),
                "data-minimum-input-length": 2,
                "data-placeholder": "Autour de (Lyon, Lille, Paris…)",
            }
        ),
    )
    category = forms.TypedChoiceField(
        coerce=data_inclusion_v1.Categorie,
        empty_value="",
        choices=[("", "Sélectionnez une thématique")] + [(c.value, c.label) for c in data_inclusion_v1.Categorie],
        label="Sélectionnez une thématique",
        widget=Select2Widget(
            attrs={"data-placeholder": "Sélectionnez une thématique"},
        ),
    )
    thematics = forms.MultipleChoiceField(
        choices=[(t.value, t.label) for t in data_inclusion_v1.Thematique],
        label="Besoin",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    reception = forms.ChoiceField(
        choices=[(RECEPTION_ALL, "Tous")] + [(t.value, t.label) for t in data_inclusion_v1.ModeAccueil],
        initial=data_inclusion_v1.ModeAccueil.EN_PRESENTIEL.value,
        label="Mode d'accueil",
        required=False,
        widget=forms.RadioSelect,
    )
    services = forms.MultipleChoiceField(
        choices=[(t.value, t.label) for t in data_inclusion_v1.TypeService],
        label="Type de service",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not_cleaned_category := self.data.get("category"):
            self.fields["thematics"].choices = [
                (t.value, t.label) for t in data_inclusion_v1.Thematique if t.value.startswith(not_cleaned_category)
            ]

    def clean_reception(self):
        reception = self.cleaned_data["reception"]
        return self.fields["reception"].initial if not reception else reception


class NewSavedSearchForm(forms.ModelForm):
    prefix = "saved_search"

    class Meta:
        model = SavedSearch
        fields = ["name", "query_params"]
        labels = {"name": "Nom de cette recherche"}
        widgets = {
            "query_params": forms.HiddenInput,
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.user = user

    def clean_query_params(self):
        query_params = self.cleaned_data["query_params"]
        query_dict = QueryDict(query_params, mutable=True)

        # We don’t want to save the page number nor the job seeker for whom we might be applying
        query_dict.pop("page", None)
        query_dict.pop("job_seeker_public_id", None)

        return query_dict.urlencode()

    def clean(self):
        super().clean()
        saved_searches_count = SavedSearch.objects.filter(user=self.instance.user).count()
        if saved_searches_count >= MAX_SAVED_SEARCHES_COUNT:
            raise forms.ValidationError(
                f"Le nombre maximum de recherches enregistrées ({MAX_SAVED_SEARCHES_COUNT}) a été atteint."
            )

    def _post_clean(self):
        super()._post_clean()
        try:
            # Validate UniqueConstraint(fields=["user", "name"], …) despite user field not being in the form
            self.instance.validate_constraints()
        except forms.ValidationError as e:
            self._update_errors(e)
