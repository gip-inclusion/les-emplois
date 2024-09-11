from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from itou.asp.models import Commune, Country
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class BirthPlaceAndCountryMixin(forms.ModelForm):
    with_birthdate_field = None

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
                "data-ajax--url": SimpleLazyObject(lambda: reverse("autocomplete:communes")),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 1,
                "data-placeholder": "Nom de la commune",
                "data-disable-target": "#id_birth_country",
                "data-target-value": SimpleLazyObject(lambda: f"{Country.objects.get(code=Country._CODE_FRANCE).pk}"),
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # with_birthdate_field indicates if JS is needed to link birthdate & birth_place fields
        if self.with_birthdate_field is None:
            self.with_birthdate_field = "birthdate" in self.fields

        if self.with_birthdate_field:
            self.fields["birth_place"].widget.attrs |= {"data-select2-link-with-birthdate": "id_birthdate"}

    def get_birth_date(self):
        return self.cleaned_data.get("birthdate", getattr(self, "birthdate", None))

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
                self.cleaned_data["birth_country"] = Country.objects.get(code=Country._CODE_FRANCE)
            else:
                # Display the error above the field instead of top of page.
                self.add_error("birth_country", "Le pays de naissance est obligatoire.")

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

    def treat_birth_fields(self):
        # class targets User and JobSeekerProfile models
        jobseeker_profile = self.instance.jobseeker_profile if hasattr(self.instance, "jobseeker_profile") else self.instance

        try:
            jobseeker_profile.birth_place = self.cleaned_data.get("birth_place")
            jobseeker_profile.birth_country = self.cleaned_data.get("birth_country")
            jobseeker_profile._clean_birth_fields()
        except ValidationError as e:
            self._update_errors(e)

    def _post_clean(self):
        super()._post_clean()
        self.treat_birth_fields()
