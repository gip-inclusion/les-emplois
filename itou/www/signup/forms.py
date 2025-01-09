from allauth.account.forms import BaseSignupForm, SignupForm
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.fields import BLANK_CHOICE_DASH
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from itou.asp.forms import BirthPlaceAndCountryMixin
from itou.common_apps.address.departments import DEPARTMENTS
from itou.prescribers.enums import CHOOSABLE_PRESCRIBER_KINDS
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import Title, UserKind
from itou.users.forms import validate_francetravail_email
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.apis import api_entreprise, geocoding as api_geocoding
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.validators import validate_birthdate, validate_code_safir, validate_nir, validate_siren, validate_siret
from itou.utils.widgets import DuetDatePickerWidget


def _get_organization_data_from_api(siret):
    # Fetch name and address from API entreprise.
    establishment, error = api_entreprise.etablissement_get_or_error(siret)
    if error:
        raise forms.ValidationError(error)

    if establishment.is_closed:
        raise forms.ValidationError("La base Sirene indique que l'établissement est fermé.")

    # Perform another API call to fetch geocoding data.
    address_fields = [
        establishment.address_line_1,
        # `address_line_2` is omitted on purpose because it tends to return no results with the BAN API.
        establishment.post_code,
        establishment.city,
        establishment.department,
    ]
    address_on_one_line = ", ".join([field for field in address_fields if field])
    try:
        geocoding_data = api_geocoding.get_geocoding_data(address_on_one_line, post_code=establishment.post_code)
    except GeocodingDataError:
        geocoding_data = {}

    return {
        "siret": siret,
        "is_head_office": establishment.is_head_office,
        "name": establishment.name,
        "address_line_1": establishment.address_line_1,
        "address_line_2": establishment.address_line_2,
        "post_code": establishment.post_code,
        "city": establishment.city,
        "department": establishment.department,
        "longitude": geocoding_data.get("longitude"),
        "latitude": geocoding_data.get("latitude"),
        "geocoding_score": geocoding_data.get("score"),
    }


class FullnameFormMixin(forms.Form):
    first_name = forms.CharField(
        label="Prénom",
        max_length=User._meta.get_field("first_name").max_length,
    )

    last_name = forms.CharField(
        label="Nom",
        max_length=User._meta.get_field("last_name").max_length,
    )


class ChooseUserKindSignupForm(forms.Form):
    kind = forms.ChoiceField(
        widget=forms.RadioSelect,
        choices=[(e.value, e.label) for e in [UserKind.JOB_SEEKER, UserKind.PRESCRIBER, UserKind.EMPLOYER]],
    )


class JobSeekerSituationForm(forms.Form):
    ERROR_NOTHING_CHECKED = (
        "Si vous êtes dans l’une des situations ci-dessous, vous devez cocher au moins une case  avant de continuer"
    )

    SITUATIONS_CHOICES = (
        ("rsa", "Bénéficiaire du RSA (revenu de solidarité active)"),
        ("ass", "Allocataire ASS (allocation spécifique de solidarité)"),
        ("aah", "Allocataire AAH (allocation adulte handicapé) ou bénéficiaire d'une RQTH"),
        ("pe", "Inscrit à France Travail depuis plus de 2 ans (inscription en continu)"),
        ("autre", "Autre"),
    )

    ELIGIBLE_SITUATION = ["rsa", "ass", "aah", "pe"]

    situation = forms.MultipleChoiceField(
        label="",
        choices=SITUATIONS_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-checkbox-greater-spacing"}),
        error_messages={"required": ERROR_NOTHING_CHECKED},
    )


class JobSeekerSignupForm(BirthPlaceAndCountryMixin, FullnameFormMixin, BaseSignupForm):
    birthdate = forms.DateField(
        label="Date de naissance",
        required=True,
        validators=[validate_birthdate],
        widget=DuetDatePickerWidget(
            {
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        ),
    )
    nir = forms.CharField(
        label="Numéro de sécurité sociale",
        required=True,
        max_length=21,  # 15 + 6 white spaces
        strip=True,
        validators=[validate_nir],
        widget=forms.TextInput(
            attrs={
                "placeholder": "2 69 05 49 588 157 80",
            }
        ),
    )
    title = forms.ChoiceField(required=True, label="Civilité", choices=BLANK_CHOICE_DASH + Title.choices)

    _nir_submitted = None
    _email_submitted = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["placeholder"] = "adresse@email.fr"
        self.fields["first_name"].widget.attrs["placeholder"] = "Dominique"
        self.fields["last_name"].widget.attrs["placeholder"] = "Durand"
        self.fields["last_name"].label = "Nom de famille"
        self.fields["birth_place"].help_text = (
            "La commune de naissance est obligatoire lorsque vous êtes né en France. "
            "Elle ne doit pas être renseignée si vous êtes né à l'étranger."
        )

    def clean_email(self):
        email = super().clean_email()
        if email.endswith(global_constants.POLE_EMPLOI_EMAIL_SUFFIX):
            raise ValidationError("Vous ne pouvez pas utiliser un e-mail Pôle emploi pour un candidat.")
        if email.endswith(global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX):
            raise ValidationError("Vous ne pouvez pas utiliser un e-mail France Travail pour un candidat.")
        if User.objects.filter(email=email).exists():
            self._email_submitted = email
            raise ValidationError("Un autre utilisateur utilise déjà cette adresse e-mail.")
        return email

    def clean_nir(self):
        nir = self.cleaned_data["nir"].replace(" ", "")
        if User.objects.filter(jobseeker_profile__nir=nir).exists():
            self._nir_submitted = nir
            raise ValidationError("Un compte avec ce numéro existe déjà.")
        return nir


class JobSeekerSignupWithOptionalNirForm(JobSeekerSignupForm):
    """We allow users with a temporary NIR to skip NIR submission"""

    skip = forms.BooleanField(widget=forms.HiddenInput(), initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nir"].required = False
        self.fields["nir"].widget.attrs["placeholder"] = ""
        self.data = self.data.dict() | {"nir": ""}

    def clean_nir(self):
        nir = self.cleaned_data["nir"].replace(" ", "")
        if nir == "":
            return ""
        return super().clean_nir()


class JobSeekerCredentialsSignupForm(SignupForm):
    first_name = forms.CharField(disabled=True, required=False, label="Prénom")
    last_name = forms.CharField(disabled=True, required=False, label="Nom")
    birthdate = forms.DateField(disabled=True, required=False, label="Date de naissance")
    nir = forms.CharField(disabled=True, required=False, label="Numéro de sécurité sociale")
    email = forms.EmailField(disabled=True, required=False, label="Adresse e-mail")

    prior_cleaned_data = None

    def __init__(self, prior_cleaned_data, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # data cleaned by earlier forms in the process - saved at the end
        self.prior_cleaned_data = prior_cleaned_data
        # NOTE: have to re-assert these values because they are overridden by allauth SignupForm.init
        self.fields["email"].required = False
        self.fields["email"].label = "Adresse e-mail"
        self.fields["email"].initial = prior_cleaned_data.get("email")
        self.fields["first_name"].initial = prior_cleaned_data.get("first_name")
        self.fields["last_name"].initial = prior_cleaned_data.get("last_name")
        self.fields["birthdate"].initial = prior_cleaned_data.get("birthdate")
        self.fields["nir"].initial = prior_cleaned_data.get("nir")
        birth_location_fields = forms.fields_for_model(JobSeekerProfile, fields=["birth_place", "birth_country"])
        for fieldname, field in birth_location_fields.items():
            field.disabled = True
            field.initial = prior_cleaned_data[fieldname]
            field.queryset = field.queryset.filter(pk=field.initial)
        self.fields.update(birth_location_fields)

        for password_field in [self.fields["password1"], self.fields["password2"]]:
            password_field.widget.attrs["placeholder"] = "**********"
        self.fields["password1"].help_text = (
            f"Le mot de passe doit contenir au moins {settings.PASSWORD_MIN_LENGTH} caractères et 3 des 4 types "
            "suivants : majuscules, minuscules, chiffres, caractères spéciaux."
        )

    def save(self, request):
        # Avoid django-allauth to call its own often failing `generate_unique_username`
        # function by forcing a username.
        self.cleaned_data["username"] = User.generate_unique_username()
        # Create the user.
        self.user_kind = UserKind.JOB_SEEKER
        user = super().save(request)
        user.title = self.prior_cleaned_data["title"]
        user.first_name = self.prior_cleaned_data["first_name"]
        user.last_name = self.prior_cleaned_data["last_name"]
        user.save()
        user.jobseeker_profile.nir = self.prior_cleaned_data["nir"]
        user.jobseeker_profile.birthdate = self.prior_cleaned_data["birthdate"]
        try:
            user.jobseeker_profile.birth_place_id = self.prior_cleaned_data["birth_place"]
            user.jobseeker_profile.birth_country_id = self.prior_cleaned_data["birth_country"]
        except KeyError:
            # TODO: Remove try-except next week.
            # Users signing up during deployment won’t have these in their session.
            pass
        user.jobseeker_profile.save()

        return user


# SIAEs signup.
# ------------------------------------------------------------------------------------------


class CompanySearchBySirenForm(forms.Form):
    siren = forms.CharField(
        label="Numéro SIREN de votre structure",
        min_length=9,
        max_length=9,
        validators=[validate_siren],
        help_text="Le numéro SIREN contient 9 chiffres.",
    )


class CompanySiaeSelectForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.siaes = kwargs.pop("siaes")
        super().__init__(*args, **kwargs)
        self.fields["siaes"].queryset = self.siaes

    siaes = forms.ModelChoiceField(queryset=None, widget=forms.RadioSelect)


class CheckAlreadyExistsForm(forms.Form):
    siret = forms.CharField(
        label="Numéro de SIRET de votre organisation",
        # `max_length` is skipped so that we can allow an arbitrary number of spaces in the user-entered value.
        min_length=14,
        help_text=mark_safe(
            "Retrouvez facilement votre numéro SIRET à partir du nom de votre organisation sur le site "
            '<a href="https://sirene.fr/" rel="noopener" target="_blank">sirene.fr</a>'
        ),
    )
    department = forms.ChoiceField(
        label="Département",
        choices=DEPARTMENTS.items(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.org_data = None
        self.fields["siret"].widget.attrs["placeholder"] = "Numéro à 14 chiffres"

    def clean_siret(self):
        siret = self.cleaned_data["siret"].replace(" ", "")
        validate_siret(siret)

        return siret


class FacilitatorSearchForm(CheckAlreadyExistsForm):
    department = None

    def clean(self):
        super().clean()
        self.org_data = _get_organization_data_from_api(self.cleaned_data["siret"])


# Prescribers signup.
# ------------------------------------------------------------------------------------------
class PrescriberRequestInvitationForm(FullnameFormMixin):
    email = forms.EmailField(
        label="Adresse e-mail",
        required=True,
        widget=forms.TextInput(
            attrs={
                "type": "email",
                "placeholder": "jeandupont@exemple.com",
                "autocomplete": "off",
            }
        ),
    )


class PrescriberChooseOrgKindForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.siret = kwargs.pop("siret")
        self.org_data = None
        super().__init__(*args, **kwargs)

    kind = forms.ChoiceField(
        label="Pour qui travaillez-vous ?",
        widget=forms.RadioSelect,
        choices=CHOOSABLE_PRESCRIBER_KINDS,
    )

    def clean_kind(self):
        # Check if the couple "type / siret" already exist
        kind = self.cleaned_data["kind"]
        org = PrescriberOrganization.objects.filter(siret=self.siret, kind=kind).first()
        if org:
            error = "« {} » utilise déjà ce type d'organisation avec le même SIRET ({})."
            error_args = [org.display_name, self.siret]
            # Get the first member to display their name and the link to the invitation request
            member = org.prescribermembership_set.first()
            if member:
                error += (
                    " Pour rejoindre cette organisation, vous devez obtenir une invitation de : {} {}."
                    ' <a href="{}">Demander une invitation</a>'
                )
                error_args += [
                    member.user.first_name.title(),
                    member.user.last_name[0].upper(),
                    reverse("signup:prescriber_request_invitation", args=[member.id]),
                ]
            raise forms.ValidationError(format_html(error, *error_args))
        return kind

    def clean(self):
        super().clean()
        self.org_data = _get_organization_data_from_api(self.siret)


class PrescriberChooseKindForm(forms.Form):
    KIND_AUTHORIZED_ORG = "authorized_org"
    KIND_UNAUTHORIZED_ORG = "unauthorized_org"

    KIND_CHOICES = (
        (KIND_AUTHORIZED_ORG, "Pour une organisation habilitée"),
        (KIND_UNAUTHORIZED_ORG, "Pour une organisation non-habilitée"),
    )

    kind = forms.ChoiceField(
        label="Pour qui travaillez-vous ?",
        choices=KIND_CHOICES,
        widget=forms.RadioSelect,
    )


class PrescriberConfirmAuthorizationForm(forms.Form):
    CONFIRM_AUTHORIZATION_CHOICES = (
        (1, "Oui, je confirme que mon organisation est habilitée"),
        (0, "Non, mon organisation n’est pas habilitée"),
    )

    confirm_authorization = forms.TypedChoiceField(
        label="Votre habilitation est-elle officialisée par arrêté préfectoral ?",
        choices=CONFIRM_AUTHORIZATION_CHOICES,
        widget=forms.RadioSelect,
        coerce=int,
    )


class PrescriberPoleEmploiSafirCodeForm(forms.Form):
    """
    Retrieve a PrescriberOrganization from the SAFIR code.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pole_emploi_org = None

    safir_code = forms.CharField(
        max_length=5,
        label="Code SAFIR",
        validators=[validate_code_safir],
        help_text="Le code SAFIR contient 5 chiffres.",
    )

    def clean_safir_code(self):
        safir_code = self.cleaned_data["safir_code"]
        self.pole_emploi_org = PrescriberOrganization.objects.by_safir_code(safir_code)
        if not self.pole_emploi_org:
            error = "Ce code SAFIR est inconnu."
            raise forms.ValidationError(error)
        return safir_code


class PrescriberCheckPEemail(forms.Form):
    email = forms.EmailField(
        label="Adresse e-mail",
        required=True,
        widget=forms.TextInput(
            attrs={
                "type": "email",
                "autocomplete": "off",
            }
        ),
    )

    def clean_email(self):
        return validate_francetravail_email(self.cleaned_data["email"])
