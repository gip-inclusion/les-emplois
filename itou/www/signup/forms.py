from allauth.account.forms import SignupForm
from django import forms
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError
from django.utils.http import urlsafe_base64_decode

from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.siaes.models import Siae, SiaeMembership
from itou.users.models import User
from itou.utils.apis.api_entreprise import EtablissementAPI
from itou.utils.apis.geocoding import get_geocoding_data
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_code_safir, validate_siren, validate_siret


BLANK_CHOICE = (("", "---------"),)


class FullnameFormMixin(forms.Form):
    first_name = forms.CharField(
        label="Prénom",
        max_length=User._meta.get_field("first_name").max_length,
        required=True,
        strip=True,
    )

    last_name = forms.CharField(
        label="Nom",
        max_length=User._meta.get_field("last_name").max_length,
        required=True,
        strip=True,
    )


class JobSeekerSignupForm(FullnameFormMixin, SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()

    def clean_email(self):
        email = super().clean_email()
        if email.endswith(settings.POLE_EMPLOI_EMAIL_SUFFIX):
            raise ValidationError("Vous ne pouvez pas utiliser un e-mail Pôle emploi pour un candidat.")
        return email

    def save(self, request):
        # Avoid django-allauth to call its own often failing `generate_unique_username`
        # function by forcing a username.
        self.cleaned_data["username"] = User.generate_unique_username()
        # Create the user.

        user = super().save(request)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_job_seeker = True
        user.save()

        return user


# SIAEs signup.
# ------------------------------------------------------------------------------------------


class SiaeSearchBySirenForm(forms.Form):

    siren = forms.CharField(
        label="Numéro SIREN de votre structure",
        min_length=9,
        max_length=9,
        validators=[validate_siren],
        help_text="Le numéro SIREN contient 9 chiffres.",
    )


class SiaeSelectForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.siaes = kwargs.pop("siaes")
        super().__init__(*args, **kwargs)
        self.fields["siaes"].queryset = self.siaes

    siaes = forms.ModelChoiceField(queryset=None, widget=forms.RadioSelect)


class SiaeSignupForm(FullnameFormMixin, SignupForm):
    """
    Second of two forms of siae signup process.
    This is the final form where the signup actually happens
    on the siae identified by the first form.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["placeholder"] = "Adresse e-mail professionnelle"
        self.fields["email"].help_text = (
            "Utilisez plutôt votre adresse e-mail professionnelle, "
            "cela nous permettra de vous identifier plus facilement comme membre de cette structure."
        )
        self.fields["kind"].widget.attrs["readonly"] = True
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()
        self.fields["siret"].widget.attrs["readonly"] = True
        self.fields["siae_name"].widget.attrs["readonly"] = True

    kind = forms.CharField(
        label="Type de votre structure",
        help_text="Ce champ n'est pas modifiable.",
        required=True,
    )

    siret = forms.CharField(
        label="Numéro SIRET de votre structure",
        help_text="Ce champ n'est pas modifiable.",
        required=True,
    )

    siae_name = forms.CharField(
        label="Nom de votre structure",
        help_text="Ce champ n'est pas modifiable.",
        required=True,
    )

    encoded_siae_id = forms.CharField(widget=forms.HiddenInput())

    token = forms.CharField(widget=forms.HiddenInput())

    def save(self, request):
        # Avoid django-allauth to call its own often failing `generate_unique_username`
        # function by forcing a username.
        self.cleaned_data["username"] = User.generate_unique_username()
        # Create the user.
        user = super().save(request)

        if self.check_siae_signup_credentials():
            siae = self.get_siae()
        else:
            raise RuntimeError("This should never happen.")

        user.is_siae_staff = True
        user.save()

        membership = SiaeMembership()
        membership.user = user
        membership.siae = siae
        # Only the first member becomes an admin.
        membership.is_siae_admin = siae.active_members.count() == 0
        membership.save()

        return user

    def get_encoded_siae_id(self):
        if "encoded_siae_id" in self.initial:
            return self.initial["encoded_siae_id"]
        return self.data["encoded_siae_id"]

    def get_token(self):
        if "token" in self.initial:
            return self.initial["token"]
        return self.data["token"]

    def get_siae(self):
        if not self.get_encoded_siae_id():
            return None
        siae_id = int(urlsafe_base64_decode(self.get_encoded_siae_id()))
        siae = Siae.objects.active().filter(pk=siae_id).first()
        return siae

    def check_siae_signup_credentials(self):
        siae = self.get_siae()
        return siae_signup_token_generator.check_token(siae=siae, token=self.get_token())

    def get_initial(self):
        siae = self.get_siae()
        return {
            "encoded_siae_id": self.get_encoded_siae_id(),
            "token": self.get_token(),
            "siret": siae.siret,
            "kind": siae.kind,
            "siae_name": siae.display_name,
        }


# Prescribers signup.
# ------------------------------------------------------------------------------------------


class PrescriberIsPoleEmploiForm(forms.Form):

    IS_POLE_EMPLOI_CHOICES = (
        (1, "Oui"),
        (0, "Non"),
    )

    is_pole_emploi = forms.TypedChoiceField(
        label="Travaillez-vous pour Pôle emploi ?",
        choices=IS_POLE_EMPLOI_CHOICES,
        widget=forms.RadioSelect,
        coerce=int,
    )


class PrescriberChooseOrgKindForm(forms.Form):

    kind = forms.ChoiceField(
        label="Pour qui travaillez-vous ?",
        widget=forms.RadioSelect,
        choices=PrescriberOrganization.Kind.choices,
    )


class PrescriberChooseKindForm(forms.Form):

    KIND_AUTHORIZED_ORG = "authorized_org"
    KIND_UNAUTHORIZED_ORG = "unauthorized_org"
    KIND_SOLO = "solo"

    KIND_CHOICES = (
        (KIND_AUTHORIZED_ORG, "Pour une organisation habilitée par le Préfet"),
        (KIND_UNAUTHORIZED_ORG, "Pour une organisation non-habilitée"),
        (KIND_SOLO, "Seul (sans organisation)"),
    )

    kind = forms.ChoiceField(
        label="Pour qui travaillez-vous ?",
        choices=KIND_CHOICES,
        widget=forms.RadioSelect,
    )


class PrescriberConfirmAuthorizationForm(forms.Form):

    CONFIRM_AUTHORIZATION_CHOICES = (
        (1, "Oui, je confirme que mon organisation est habilitée par le Préfet"),
        (0, "Non, mon organisation n’est pas habilitée par le Préfet"),
    )

    confirm_authorization = forms.TypedChoiceField(
        label="Votre habilitation est-elle officialisée par arrêté préfectoral ?",
        choices=CONFIRM_AUTHORIZATION_CHOICES,
        widget=forms.RadioSelect,
        coerce=int,
    )


class PrescriberSiretForm(forms.Form):
    """
    Retrieve info about an organization from a given SIRET.
    """

    def __init__(self, *args, **kwargs):
        # We need the kind of the SIAE to check constraint on SIRET number
        self.kind = kwargs.pop("kind", None)

        super().__init__(*args, **kwargs)
        self.org_data = None

    siret = forms.CharField(
        label="Numéro SIRET de votre organisation",
        min_length=14,
        help_text="Le numéro SIRET contient 14 chiffres.",
    )

    def clean_siret(self):

        # `max_length` is skipped so that we can allow an arbitrary number of spaces in the user-entered value.
        siret = self.cleaned_data["siret"].replace(" ", "")

        validate_siret(siret)

        # Does an org with this SIRET already exist?
        org = PrescriberOrganization.objects.filter(siret=siret, kind=self.kind).first()
        if org:
            error = f'"{org.display_name}" utilise déjà ce SIRET.'
            admin = org.get_admins().first()
            if admin:
                error += (
                    f" "
                    f"Pour rejoindre cette organisation, vous devez obtenir une invitation de son administrateur : "
                    f"{admin.first_name.title()} {admin.last_name[0].upper()}."
                )
            raise forms.ValidationError(error)

        # Fetch name and address from API entreprise.
        etablissement = EtablissementAPI(siret)

        if etablissement.error:
            raise forms.ValidationError(etablissement.error)

        if etablissement.is_closed:
            raise forms.ValidationError(etablissement.ERROR_IS_CLOSED)

        # Perform another API call to fetch geocoding data.
        address_fields = [
            etablissement.address_line_1,
            # `address_line_2` is omitted on purpose because it tends to return no results with the BAN API.
            etablissement.post_code,
            etablissement.city,
            etablissement.department,
        ]
        address_on_one_line = ", ".join([field for field in address_fields if field])
        geocoding_data = get_geocoding_data(address_on_one_line, post_code=etablissement.post_code) or {}

        self.org_data = {
            "siret": siret,
            "name": etablissement.name,
            "address_line_1": etablissement.address_line_1,
            "address_line_2": etablissement.address_line_2,
            "post_code": etablissement.post_code,
            "city": etablissement.city,
            "department": etablissement.department,
            "longitude": geocoding_data.get("longitude"),
            "latitude": geocoding_data.get("latitude"),
            "geocoding_score": geocoding_data.get("score"),
        }

        return siret


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


class PrescriberPoleEmploiUserSignupForm(FullnameFormMixin, SignupForm):
    """
    Create a new user of type prescriber and add it to the members of the given prescriber organization.
    """

    def __init__(self, *args, **kwargs):
        self.pole_emploi_org = kwargs.pop("pole_emploi_org")
        super().__init__(*args, **kwargs)
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()
        self.fields["email"].help_text = f"Exemple : nom.prenom{settings.POLE_EMPLOI_EMAIL_SUFFIX}"

    def clean_email(self):
        email = super().clean_email()
        if not email.endswith(settings.POLE_EMPLOI_EMAIL_SUFFIX):
            raise ValidationError("L'adresse e-mail doit être une adresse Pôle emploi.")
        return email

    def save(self, request):
        # Avoid django-allauth to call its own often failing `generate_unique_username`
        # function by forcing a username.
        self.cleaned_data["username"] = User.generate_unique_username()
        # Create the user.
        user = super().save(request)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_prescriber = True
        user.save()

        # The member becomes a member of the PE agency.
        membership = PrescriberMembership()
        membership.user = user
        membership.organization = self.pole_emploi_org
        # The first member becomes an admin.
        membership.is_admin = membership.organization.members.count() == 0
        membership.save()

        return user


class PrescriberUserSignupForm(FullnameFormMixin, SignupForm):
    """
    Create a new user of type prescriber and his organization (if any).
    """

    def __init__(self, *args, **kwargs):
        self.authorization_status = kwargs.pop("authorization_status")
        self.kind = kwargs.pop("kind")
        self.prescriber_org_data = kwargs.pop("prescriber_org_data")
        super().__init__(*args, **kwargs)
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()
        self.fields["email"].help_text = "Utilisez une adresse e-mail professionnelle."

    def save(self, request):
        # Avoid django-allauth to call its own often failing `generate_unique_username`
        # function by forcing a username.
        self.cleaned_data["username"] = User.generate_unique_username()
        # Create the user.
        user = super().save(request)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_prescriber = True
        user.save()

        # Create the organization if any: an orienteur may not belong to any organization.
        if self.prescriber_org_data:

            prescriber_org = PrescriberOrganization()
            prescriber_org.siret = self.prescriber_org_data["siret"]
            prescriber_org.name = self.prescriber_org_data["name"]
            prescriber_org.address_line_1 = self.prescriber_org_data["address_line_1"] or ""
            prescriber_org.address_line_2 = self.prescriber_org_data["address_line_2"] or ""
            prescriber_org.post_code = self.prescriber_org_data["post_code"]
            prescriber_org.city = self.prescriber_org_data["city"]
            prescriber_org.department = self.prescriber_org_data["department"]
            longitude = self.prescriber_org_data["longitude"]
            latitude = self.prescriber_org_data["latitude"]
            if longitude and latitude:
                prescriber_org.coords = GEOSGeometry(f"POINT({longitude} {latitude})")
            prescriber_org.geocoding_score = self.prescriber_org_data["geocoding_score"]
            prescriber_org.kind = self.kind
            prescriber_org.authorization_status = self.authorization_status
            prescriber_org.created_by = user
            prescriber_org.save()

            # The member becomes a member of the organization.
            membership = PrescriberMembership()
            membership.user = user
            membership.organization = prescriber_org
            # The first member becomes an admin.
            membership.is_admin = membership.organization.members.count() == 0
            membership.save()

            # Notify support.
            if prescriber_org.authorization_status == PrescriberOrganization.AuthorizationStatus.NOT_SET:
                prescriber_org.must_validate_prescriber_organization_email().send()

        return user
