from allauth.account.forms import SignupForm
from django import forms
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.http import urlsafe_base64_decode
from django.utils.safestring import mark_safe

from itou.common_apps.address.departments import DEPARTMENTS
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.siaes.models import Siae, SiaeMembership
from itou.users.models import User
from itou.utils.apis.api_entreprise import etablissement_get_or_error
from itou.utils.apis.geocoding import get_geocoding_data
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_code_safir, validate_nir, validate_siren, validate_siret


BLANK_CHOICE = (("", "---------"),)
FRANCE_CONNECT_PASSWORD_EXPLANATION = "Attention, ce mot de passe est celui de votre compte local et en aucun cas celui du compte que vous utilisez au travers de FranceConnect. Il vous servira uniquement lorsque vous vous connecterez avec votre adresse mail plutôt que via FranceConnect."  # noqa E501


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


class JobSeekerNirForm(forms.Form):
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

    def clean_nir(self):
        nir = self.cleaned_data["nir"].replace(" ", "")
        user_exists = User.objects.filter(nir=nir).exists()
        if user_exists:
            raise ValidationError("Un compte avec ce numéro existe déjà.")
        return nir


class JobSeekerSituationForm(forms.Form):

    ERROR_NOTHING_CHECKED = (
        "Si vous êtes dans l’une des situations ci-dessous, vous devez cocher au moins une case  avant de continuer"
    )

    SITUATIONS_CHOICES = (
        ("rsa", "Bénéficiaire du RSA (revenu de solidarité active)"),
        ("ass", "Allocataire ASS (allocation spécifique de solidarité)"),
        ("aah", "Allocataire AAH (allocation adulte handicapé) ou bénéficiaire d'une RQTH"),
        ("pe", "Inscrit à Pôle emploi depuis plus de 2 ans (inscription en continu)"),
        ("autre", "Autre"),
    )

    ELIGIBLE_SITUATION = ["rsa", "ass", "aah", "pe"]

    situation = forms.MultipleChoiceField(
        label="Quelle est votre situation ? ",
        choices=SITUATIONS_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": ERROR_NOTHING_CHECKED},
    )


class JobSeekerSignupForm(FullnameFormMixin, SignupForm):
    nir = forms.CharField(disabled=True, required=False, label="Numéro de sécurité sociale")

    def __init__(self, nir, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nir = nir
        self.fields["nir"].initial = self.nir
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()
        for password_field in [self.fields["password1"], self.fields["password2"]]:
            password_field.widget.attrs["placeholder"] = "**********"
        self.fields["email"].widget.attrs["placeholder"] = "adresse@email.fr"
        self.fields["email"].label = "Adresse e-mail"
        self.fields["first_name"].widget.attrs["placeholder"] = "Dominique"
        self.fields["last_name"].widget.attrs["placeholder"] = "Durand"
        self.fields["password1"].help_text = (
            CnilCompositionPasswordValidator().get_help_text() + " " + FRANCE_CONNECT_PASSWORD_EXPLANATION
        )

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
        if self.nir:
            user.nir = self.nir

        user.save()

        if self.nir:
            del request.session[settings.ITOU_SESSION_NIR_KEY]

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
        membership.is_admin = siae.active_members.count() == 0
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


class PrescriberCheckAlreadyExistsForm(forms.Form):

    siret = forms.CharField(
        label="Numéro de SIRET de votre organisation",
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

    def clean_siret(self):
        # `max_length` is skipped so that we can allow an arbitrary number of spaces in the user-entered value.
        siret = self.cleaned_data["siret"].replace(" ", "")
        validate_siret(siret)

        # Fetch name and address from API entreprise.
        etablissement, error = etablissement_get_or_error(siret)
        if error:
            raise forms.ValidationError(error)

        if etablissement.is_closed:
            raise forms.ValidationError("La base Sirene indique que l'établissement est fermé.")

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
            "is_head_office": etablissement.is_head_office,
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


class PrescriberRequestInvitationForm(FullnameFormMixin):
    email = forms.EmailField(
        label="E-mail",
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
        super().__init__(*args, **kwargs)

    kind = forms.ChoiceField(
        label="Pour qui travaillez-vous ?",
        widget=forms.RadioSelect,
        choices=PrescriberOrganization.Kind.choices,
    )

    def clean_kind(self):
        # Check if the couple "type / siret" already exist
        kind = self.cleaned_data["kind"]
        org = PrescriberOrganization.objects.filter(siret=self.siret, kind=kind).first()
        if org:
            error = f"« {org.display_name} » utilise déjà ce type d'organisation avec le même SIRET ({self.siret})."
            # Get the first member to display their name and the link to the invitation request
            member = org.prescribermembership_set.first()
            if member:
                url = reverse("signup:prescriber_request_invitation", args=[member.id])
                error += (
                    f" "
                    f"Pour rejoindre cette organisation, vous devez obtenir une invitation de : "
                    f"{member.user.first_name.title()} {member.user.last_name[0].upper()}."
                    f" "
                    f'<a href="{url}">Demander une invitation</a>'
                )
            raise forms.ValidationError(mark_safe(error))
        return kind


class PrescriberChooseKindForm(forms.Form):

    KIND_AUTHORIZED_ORG = "authorized_org"
    KIND_UNAUTHORIZED_ORG = "unauthorized_org"

    KIND_CHOICES = (
        (KIND_AUTHORIZED_ORG, "Pour une organisation habilitée par le Préfet"),
        (KIND_UNAUTHORIZED_ORG, "Pour une organisation non-habilitée"),
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
