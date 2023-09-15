from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.cities.models import City
from itou.common_apps.address.forms import OptionalAddressFormMixin
from itou.common_apps.nir.forms import JobSeekerNIRUpdateMixin
from itou.geo.utils import coords_to_geometry
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.users.enums import IdentityProvider
from itou.users.forms import JobSeekerProfileFieldsMixin
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.apis import geocoding as api_geocoding
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.widgets import AddressAutocompleteWidget, DuetDatePickerWidget


class SSOReadonlyMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.has_sso_provider and self.instance.identity_provider != IdentityProvider.PE_CONNECT:
            # When a user has logged in with a SSO other than PEAMU
            # it should see the field but most should be disabled
            # (that’s a requirement on FranceConnect’s side).
            disabled_fields = ["first_name", "last_name", "email", "birthdate"]
            for name in self.fields.keys():
                if name in disabled_fields:
                    self.fields[name].disabled = True


class JobSeekerAddressForm(forms.ModelForm):
    address_line_1 = forms.CharField(
        label="Adresse", widget=forms.TextInput(attrs={"placeholder": "102 Quai de Jemmapes"})
    )
    address_line_2 = forms.CharField(
        label="Complément d'adresse", widget=forms.TextInput(attrs={"placeholder": "Appartement 16"}), required=False
    )
    post_code = forms.IntegerField(label="Code postal", widget=forms.NumberInput(attrs={"placeholder": "75010"}))
    insee_code = forms.CharField(widget=forms.HiddenInput(), required=False)
    latitude = forms.FloatField(widget=forms.HiddenInput(), required=False)
    longitude = forms.FloatField(widget=forms.HiddenInput(), required=False)
    geocoding_score = forms.FloatField(widget=forms.HiddenInput(), required=False)
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
            "latitude",
            "longitude",
            "geocoding_score",
            "ban_api_resolved_address",
        ]

        for field_name in js_handled_fields:
            self.fields[field_name].widget.attrs["class"] = f"js-{field_name.replace('_', '-')}"
            self.fields[field_name].required = False

        choices = []
        address_choice = None

        if kwargs["data"] and "ban_api_resolved_address" in kwargs["data"]:
            # The user did a select2 choice, we should refill the chosen address if there was a form error
            address_choice = kwargs["data"]["ban_api_resolved_address"]

        if self.instance and address_choice is None:
            job_seeker = self.instance
            if job_seeker.address_line_1:
                address_choice = job_seeker.geocoding_address

        if address_choice is not None:
            choices = [(0, address_choice)]

        self.fields["address_for_autocomplete"] = forms.CharField(
            label="Adresse",
            required=True,
            widget=AddressAutocompleteWidget(
                choices=choices,
            ),
            help_text=(
                "Si votre adresse ne s’affiche pas, merci de renseigner votre ville uniquement en utilisant "
                "votre code postal et d’utiliser le Complément d’adresse pour renseigner vos numéro et nom de rue."
            ),
        )

        if choices:
            self.initial["address_for_autocomplete"] = 0

    class Meta:
        model = User
        fields = [
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "geocoding_score",
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

        if fill_mode == "fallback":
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
                self.instance.coords = coords_to_geometry(
                    lat=geocoding_data.get("latitude"), lon=geocoding_data.get("longitude")
                )
            except GeocodingDataError:
                raise ValidationError("Impossible de géolocaliser votre adresse. Veuillez en saisir une autre.")

        if self.cleaned_data["post_code"] is None:
            self.cleaned_data["post_code"] = ""

        return self.cleaned_data


class EditJobSeekerInfoForm(
    JobSeekerNIRUpdateMixin, JobSeekerProfileFieldsMixin, JobSeekerAddressForm, SSOReadonlyMixin, forms.ModelForm
):
    """
    Edit a job seeker profile.
    """

    PROFILE_FIELDS = ["pole_emploi_id", "lack_of_pole_emploi_id_reason", "nir", "lack_of_nir_reason"]

    email = forms.EmailField(
        label="Adresse électronique",
        disabled=True,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    class Meta:
        model = User
        fields = [
            "email",
            "title",
            "first_name",
            "last_name",
            "birthdate",
            "phone",
        ] + JobSeekerAddressForm.Meta.fields

        help_texts = {
            "birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978",
            "phone": "L'ajout du numéro de téléphone permet à l'employeur de vous contacter plus facilement.",
        }

    def __init__(self, *args, **kwargs):
        editor = kwargs.get("editor", None)
        super().__init__(*args, **kwargs)
        assert self.instance.is_job_seeker, self.instance

        self.fields["title"].required = True
        self.fields["birthdate"].required = True
        self.fields["birthdate"].widget = DuetDatePickerWidget(
            attrs={
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )

        # Noboby can edit its own email.
        if self.instance.identity_provider == IdentityProvider.FRANCE_CONNECT:
            # If the job seeker uses France Connect, point them to the modification process
            self.fields["email"].help_text = (
                "Si vous souhaitez modifier votre adresse e-mail merci de "
                f"<a href='{global_constants.ITOU_HELP_CENTER_URL}/requests/new' target='_blank'>"
                "contacter notre support technique</a>"
            )
        elif editor and editor.can_edit_email(self.instance):
            # Only prescribers and employers can edit the job seeker's email here under certain conditions
            self.fields["email"].disabled = False
        else:
            # Otherwise, hide the field
            self.fields["email"].widget = forms.HiddenInput()

    def clean(self):
        super().clean()
        JobSeekerProfile.clean_pole_emploi_fields(self.cleaned_data)

    def save(self, commit=True):
        self.instance.last_checked_at = timezone.now()

        if self.instance.ban_api_resolved_address == "":
            self.instance.ban_api_resolved_address = None

        return super().save(commit=commit)


class EditUserInfoForm(OptionalAddressFormMixin, SSOReadonlyMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "phone",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "city_slug",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        assert not self.instance.is_job_seeker, self.instance

    def save(self, commit=True):
        self.instance.last_checked_at = timezone.now()
        return super().save(commit=commit)


class EditUserEmailForm(forms.Form):
    email = forms.EmailField(
        label="Nouvelle adresse e-mail",
        widget=forms.EmailInput(attrs={"placeholder": "prenom.nom@example.com"}),
        required=True,
    )
    email_confirmation = forms.EmailField(
        label="Confirmation de l'adresse e-mail",
        widget=forms.EmailInput(attrs={"placeholder": "prenom.nom@example.com"}),
        required=True,
    )

    def __init__(self, *args, **kwargs):
        self.user_email = kwargs.pop("user_email")
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        email = self.cleaned_data.get("email")
        email_confirmation = self.cleaned_data.get("email_confirmation")
        if email != email_confirmation:
            raise ValidationError("Les deux adresses sont différentes.")
        return self.cleaned_data

    def clean_email(self):
        email = self.cleaned_data["email"]
        if email == self.user_email:
            raise ValidationError("Veuillez indiquer une adresse différente de l'actuelle.")
        if User.objects.filter(email=email):
            raise ValidationError("Cette adresse est déjà utilisée par un autre utilisateur.")
        return email


class EditNewJobAppEmployersNotificationForm(forms.Form):
    spontaneous = forms.BooleanField(label="Candidatures spontanées", required=False)

    def __init__(self, recipient, company, *args, **kwargs):
        self.recipient = recipient
        self.company = company
        super().__init__(*args, **kwargs)
        self.fields["spontaneous"].initial = NewSpontaneousJobAppEmployersNotification.is_subscribed(self.recipient)

        if self.company.job_description_through.exists():
            default_pks = self.company.job_description_through.values_list("pk", flat=True)
            self.subscribed_pks = NewQualifiedJobAppEmployersNotification.recipient_subscribed_pks(
                recipient=self.recipient, default_pks=default_pks
            )
            choices = [
                (job_description.pk, job_description.display_name)
                for job_description in self.company.job_description_through.all()
            ]
            self.fields["qualified"] = forms.MultipleChoiceField(
                label="Fiches de poste",
                required=False,
                widget=forms.CheckboxSelectMultiple(),
                choices=choices,
                initial=self.subscribed_pks,
            )

    def save(self):
        if self.cleaned_data.get("spontaneous"):
            NewSpontaneousJobAppEmployersNotification.subscribe(recipient=self.recipient)
        else:
            NewSpontaneousJobAppEmployersNotification.unsubscribe(recipient=self.recipient)

        if self.company.job_description_through.exists():
            to_subscribe_pks = self.cleaned_data.get("qualified")
            NewQualifiedJobAppEmployersNotification.replace_subscriptions(
                recipient=self.recipient, subscribed_pks=to_subscribe_pks
            )
