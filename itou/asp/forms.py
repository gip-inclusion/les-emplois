from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.functional import SimpleLazyObject

from itou.asp.models import Commune, Country
from itou.users.models import JobSeekerProfile
from itou.utils.validators import validate_birth_location
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class BirthPlaceModelForm(forms.ModelForm):
    birth_country = forms.ModelChoiceField(Country.objects, label="Pays de naissance", required=False)
    birth_place = forms.ModelChoiceField(
        queryset=Commune.objects,
        label="Commune de naissance",
        help_text=(
            "La commune de naissance est obligatoire lorsque le salarié est né en France. "
            "Elle ne doit pas être renseignée s’il est né à l'étranger."
        ),
        required=False,
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": reverse_lazy("autocomplete:communes"),
                "data-ajax--cache": "true",
                "data-ajax--delay": 250,
                "data-ajax--type": "GET",
                "data-minimum-input-length": 1,
                "data-placeholder": "Nom de la commune",
                "data-disable-target": "#id_birth_country",
                "data-target-value": SimpleLazyObject(lambda: f"{Country.france_id}"),
            }
        ),
    )

    class Meta:
        model = JobSeekerProfile
        fields = ["birth_place", "birth_country"]

    def get_birth_date(self):
        raise NotImplementedError

    def clean(self):
        super().clean()

        birth_place = self.cleaned_data.get("birth_place")
        birth_country = self.cleaned_data.get("birth_country")
        birth_date = self.get_birth_date()

        if not birth_country:
            # Selecting a birth place sets the birth country field to France and disables it.
            # However, disabled fields are ignored by Django.
            # That's also why we can't make it mandatory.
            # See utils.js > toggleDisableAndSetValue
            if birth_place:
                birth_country = Country.objects.get(code=Country.INSEE_CODE_FRANCE)
                self.cleaned_data["birth_country"] = birth_country
            else:
                # Display the error above the field instead of top of page.
                self.add_error("birth_country", "Le pays de naissance est obligatoire.")

        try:
            validate_birth_location(birth_country, birth_place)
        except ValidationError as e:
            self.add_error(None, e)

        # Country coherence is done at model level (users.User)
        # Here we must add coherence between birthdate and communes
        # existing at this period (not a simple check of existence)
        if birth_place and birth_date:
            try:
                self.cleaned_data["birth_place"] = Commune.objects.by_insee_code_and_period(
                    birth_place.code, birth_date
                )
            except Commune.DoesNotExist:
                msg = (
                    f"Le code INSEE {birth_place.code} n'est pas référencé par l'ASP en date du {birth_date:%d/%m/%Y}"
                )
                self.add_error("birth_place", msg)


class BirthPlaceWithBirthdateModelForm(BirthPlaceModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birth_place"].widget.attrs["data-select2-link-with-birthdate"] = "id_birthdate"

    def get_birth_date(self):
        return self.cleaned_data.get("birthdate")


class BirthPlaceWithoutBirthdateModelForm(BirthPlaceModelForm):
    def __init__(self, birthdate, *args, **kwargs):
        self.birthdate = birthdate
        super().__init__(*args, **kwargs)

    def get_birth_date(self):
        return self.birthdate
