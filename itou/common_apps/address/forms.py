import django.forms as forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.cities.models import City
from itou.geo.utils import coords_to_geometry
from itou.users.models import User
from itou.utils.apis import geocoding as api_geocoding
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.widgets import JobSeekerAddressAutocompleteWidget


class JobSeekerAddressForm(forms.ModelForm):
    address_line_1 = forms.CharField(
        label="Adresse", widget=forms.TextInput(attrs={"placeholder": "102 Quai de Jemmapes"})
    )
    address_line_2 = forms.CharField(
        label="Complément d'adresse", widget=forms.TextInput(attrs={"placeholder": "Appartement 16"}), required=False
    )
    post_code = forms.CharField(label="Code postal", widget=forms.TextInput(attrs={"placeholder": "75010"}))
    insee_code = forms.CharField(widget=forms.HiddenInput(), required=False)
    ban_api_resolved_address = forms.CharField(widget=forms.HiddenInput(), required=False)
    fill_mode = forms.CharField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        js_handled_fields = [
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "insee_code",
            "ban_api_resolved_address",
        ]

        for field_name in js_handled_fields:
            self.fields[field_name].widget.attrs["class"] = f"js-{field_name.replace('_', '-')}"
            self.fields[field_name].required = False

        initial_data = {}

        # Manage form update/post and creation
        if "data" in kwargs and kwargs["data"] is not None:
            initial_data = kwargs["data"]
        elif "initial" in kwargs and kwargs["initial"] is not None:
            initial_data = kwargs["initial"]

        self.fields["address_for_autocomplete"] = forms.CharField(
            label="Adresse actuelle",
            required=True,
            widget=JobSeekerAddressAutocompleteWidget(initial_data=initial_data, job_seeker=self.instance),
            initial=0,
            help_text=(
                "Si votre adresse ne s’affiche pas, merci de renseigner votre ville uniquement en utilisant "
                "votre code postal et d’utiliser le Complément d’adresse pour renseigner vos numéro et nom de rue."
            ),
        )

    class Meta:
        model = User
        fields = [
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "ban_api_resolved_address",
        ]

    def clean_insee_code(self):
        insee_code = self.cleaned_data["insee_code"]
        city = None

        if insee_code:
            try:
                city = City.objects.get(code_insee=insee_code)
            except City.DoesNotExist:
                raise ValidationError("Cette ville n'existe pas dans le référentiel de l'INSEE.")

        if city:
            self.instance.city = city.name
            self.instance.insee_city = city
            self.cleaned_data["city"] = city.name

        return insee_code

    def clean(self):
        super().clean()
        address_line_1 = self.cleaned_data.get("address_line_1")

        # Address was filled (manually with fallback or programatically with select2)
        # the address field should not be required anymore as we don't really use it
        if address_line_1:
            if "address_for_autocomplete" in self.errors:
                del self.errors["address_for_autocomplete"]
                self.cleaned_data["address_for_autocomplete"] = None

        new_address = self.cleaned_data["ban_api_resolved_address"]
        fill_mode = self.cleaned_data["fill_mode"]

        address_to_geocode = None

        if fill_mode == "ban_api" and new_address:
            # If new_address is set the user did a new select2 choice

            self.instance.address_filled_at = timezone.now()
            self.instance.geocoding_updated_at = timezone.now()

            address_to_geocode = new_address
        elif fill_mode == "fallback":
            # we should refill latitude and longitude based on the address provided
            posted_fields = [
                self.cleaned_data["address_line_1"],
                f"{self.cleaned_data['post_code']} {self.cleaned_data['city']}",
            ]
            posted_address = ", ".join([field for field in posted_fields if field])

            if posted_address != self.instance.geocoding_address:
                address_to_geocode = posted_address

        if address_to_geocode is not None:
            try:
                geocoding_data = api_geocoding.get_geocoding_data(address_to_geocode)

                if not geocoding_data:
                    raise ValidationError("Impossible de géolocaliser votre adresse. Veuillez en saisir une autre.")
            except GeocodingDataError:
                raise ValidationError(
                    "Impossible de géolocaliser votre adresse : problème de geométrie. Veuillez en saisir une autre."
                )
            else:
                self.instance.coords = coords_to_geometry(
                    lat=geocoding_data["latitude"], lon=geocoding_data["longitude"]
                )
                self.instance.geocoding_score = geocoding_data["score"]

        if self.cleaned_data["post_code"] is None:
            self.cleaned_data["post_code"] = ""

        return self.cleaned_data
