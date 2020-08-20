from allauth.account.forms import SignupForm
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.http import urlsafe_base64_decode
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy

from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.siaes.models import Siae, SiaeMembership
from itou.utils.apis.api_entreprise import EtablissementAPI
from itou.utils.apis.geocoding import get_geocoding_data
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_code_safir, validate_siret


BLANK_CHOICE = (("", "---------"),)


class FullnameFormMixin(forms.Form):
    first_name = forms.CharField(
        label=gettext_lazy("Prénom"),
        max_length=get_user_model()._meta.get_field("first_name").max_length,
        required=True,
        strip=True,
    )

    last_name = forms.CharField(
        label=gettext_lazy("Nom"),
        max_length=get_user_model()._meta.get_field("last_name").max_length,
        required=True,
        strip=True,
    )


class SelectSiaeForm(forms.Form):
    """
    First of two forms of siae signup process.
    This first form allows the user to select which siae will be joined.
    """

    DOC_OPENING_SCHEDULE_URL = (
        "https://doc.inclusion.beta.gouv.fr/presentation/quel-est-le-calendrier-de-deploiement-de-la-plateforme"
    )

    kind = forms.ChoiceField(
        label=gettext_lazy("Type de structure"), choices=BLANK_CHOICE + Siae.KIND_CHOICES, required=True
    )

    siret = forms.CharField(
        label=gettext_lazy("Numéro de SIRET"),
        min_length=14,
        max_length=14,
        validators=[validate_siret],
        strip=True,
        help_text=gettext_lazy("Saisissez 14 chiffres."),
        required=False,
    )

    email = forms.EmailField(
        label=gettext_lazy("E-mail"),
        help_text=gettext_lazy(
            "Vous êtes une SIAE ? Attention, indiquez l'e-mail utilisé "
            "par le référent technique ASP et non votre e-mail de connexion."
        ),
        required=False,
    )

    def clean(self):
        cleaned_data = super().clean()
        kind = cleaned_data.get("kind")
        siret = cleaned_data.get("siret")
        email = cleaned_data.get("email")

        if not (siret or email):
            error_message = _(
                "Merci de renseigner l'e-mail utilisé par le référent technique ASP "
                "ou un numéro de SIRET connu de nos services."
            )
            raise forms.ValidationError(error_message)

        siaes = Siae.objects.filter(kind=kind)
        if siret and email:
            # We match siaes having any of the two correct fields.
            siaes = siaes.filter(Q(siret=siret) | Q(auth_email=email))
        elif email:
            siaes = siaes.filter(auth_email=email)
        else:
            siaes = siaes.filter(siret=siret)
        # Hit the database only once.
        siaes = list(siaes)
        siaes_matching_siret = [s for s in siaes if s.siret == siret]
        # There can be at most one siret match due to (kind, siret) unicity.
        siret_exists = len(siaes_matching_siret) == 1

        def raise_form_error_for_inactive_siae():
            error_message = _("La structure que vous souhaitez rejoindre n'est plus active à ce jour.")
            raise forms.ValidationError(mark_safe(error_message))

        if siret_exists:
            if siaes_matching_siret[0].is_active:
                self.selected_siae = siaes_matching_siret[0]
            else:
                raise_form_error_for_inactive_siae()
        else:
            siaes_matching_email = [s for s in siaes if s.auth_email == email]
            email_exists = len(siaes_matching_email) > 0
            active_siaes_matching_email = [s for s in siaes_matching_email if s.is_active]
            several_siaes_share_same_email = len(active_siaes_matching_email) > 1
            email_exists_in_active_siae = len(active_siaes_matching_email) > 0

            if several_siaes_share_same_email:
                error_message = _(
                    "Votre e-mail est partagé par plusieurs structures "
                    "et votre numéro de SIRET nous est inconnu.<br>"
                    "Merci de vous rapprocher de votre service gestion "
                    "afin d'obtenir votre numéro de SIRET."
                )
                raise forms.ValidationError(mark_safe(error_message))

            if not email_exists:
                error_message = _(
                    f"Votre numéro de SIRET ou votre e-mail nous sont inconnus.<br>Merci de "
                    f'<a href="{self.DOC_OPENING_SCHEDULE_URL}">vérifier que la plateforme '
                    f"est disponible sur votre territoire</a> ou veuillez nous contacter "
                    f"à l'adresse suivante : {settings.ITOU_EMAIL_CONTACT}"
                )
                raise forms.ValidationError(mark_safe(error_message))

            if not email_exists_in_active_siae:
                raise_form_error_for_inactive_siae()

            self.selected_siae = active_siaes_matching_email[0]


class SiaeSignupForm(FullnameFormMixin, SignupForm):
    """
    Second of two forms of siae signup process.
    This is the final form where the signup actually happens
    on the siae identified by the first form.
    """

    def __init__(self, *args, **kwargs):
        super(SiaeSignupForm, self).__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["placeholder"] = _("Adresse e-mail professionnelle")
        self.fields["email"].help_text = _(
            "Utilisez plutôt votre adresse e-mail professionnelle, "
            "cela nous permettra de vous identifier plus facilement comme membre de cette structure."
        )
        self.fields["kind"].widget.attrs["readonly"] = True
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()
        self.fields["siret"].widget.attrs["readonly"] = True
        self.fields["siae_name"].widget.attrs["readonly"] = True

    kind = forms.CharField(
        label=gettext_lazy("Type de votre structure"),
        help_text=gettext_lazy("Ce champ n'est pas modifiable."),
        required=True,
    )

    siret = forms.CharField(
        label=gettext_lazy("Numéro SIRET de votre structure"),
        help_text=gettext_lazy("Ce champ n'est pas modifiable."),
        required=True,
    )

    siae_name = forms.CharField(
        label=gettext_lazy("Nom de votre structure"),
        help_text=gettext_lazy("Ce champ n'est pas modifiable."),
        required=True,
    )

    encoded_siae_id = forms.CharField(widget=forms.HiddenInput())

    token = forms.CharField(widget=forms.HiddenInput())

    def save(self, request):
        user = super().save(request)

        if self.check_siae_signup_credentials():
            siae = self.get_siae()
        else:
            raise RuntimeError("This should never happen.")

        if siae.has_members:
            siae.new_signup_warning_email_to_existing_members(user).send()

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
        siae = Siae.active.filter(pk=siae_id).first()
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


class JobSeekerSignupForm(FullnameFormMixin, SignupForm):
    def __init__(self, *args, **kwargs):
        super(JobSeekerSignupForm, self).__init__(*args, **kwargs)
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()

    def save(self, request):
        user = super().save(request)

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]

        user.is_job_seeker = True
        user.save()

        return user


# Prescribers signup.
# ------------------------------------------------------------------------------------------


class PrescriberEntryPointForm(forms.Form):

    IS_POLE_EMPLOI_CHOICES = (
        (1, gettext_lazy("Oui")),
        (0, gettext_lazy("Non")),
    )

    is_pole_emploi = forms.TypedChoiceField(
        label=gettext_lazy("Travaillez-vous pour Pôle emploi ?"),
        choices=IS_POLE_EMPLOI_CHOICES,
        widget=forms.RadioSelect,
        coerce=int,
    )


class PrescriberIdentifyOrganizationKindForm(forms.Form):

    kind = forms.ChoiceField(
        label=gettext_lazy("Pour qui travaillez-vous ?"),
        widget=forms.RadioSelect,
        choices=PrescriberOrganization.Kind.choices,
    )


class PrescriberIdentifyKindForm(forms.Form):

    KIND_AUTHORIZED_ORG = "authorized_org"
    KIND_UNAUTHORIZED_ORG = "unauthorized_org"
    KIND_SOLO = "solo"

    KIND_CHOICES = (
        (KIND_AUTHORIZED_ORG, gettext_lazy("Pour une organisation habilitée par le Préfet")),
        (KIND_UNAUTHORIZED_ORG, gettext_lazy("Pour une organisation non-habilitée")),
        (KIND_SOLO, gettext_lazy("Seul (sans organisation)")),
    )

    kind = forms.ChoiceField(
        label=gettext_lazy("Pour qui travaillez-vous ?"), choices=KIND_CHOICES, widget=forms.RadioSelect,
    )


class PrescriberConfirmAuthorizationForm(forms.Form):

    CONFIRM_AUTHORIZATION_CHOICES = (
        (1, gettext_lazy("Oui, je confirme que mon organisation est habilitée par le Préfet")),
        (0, gettext_lazy("Non, mon organisation n’est pas habilitée par le Préfet")),
    )

    confirm_authorization = forms.TypedChoiceField(
        label=gettext_lazy("Votre habilitation est-elle officialisée par arrêté préfectoral ?"),
        choices=CONFIRM_AUTHORIZATION_CHOICES,
        widget=forms.RadioSelect,
        coerce=int,
    )


class PrescriberSiretForm(forms.Form):
    """
    Retrieve info about an organization from a given SIRET.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.org_data = None

    siret = forms.CharField(
        label=gettext_lazy("Numéro SIRET de votre organisation"),
        min_length=14,
        help_text=gettext_lazy("Le numéro SIRET contient 14 chiffres."),
    )

    def clean_siret(self):

        # `max_length` is skiped so that we can allow an arbitrary number of spaces in the user-entered value.
        siret = self.cleaned_data["siret"].replace(" ", "")

        validate_siret(siret)

        # Does the org already exists?
        if PrescriberOrganization.objects.filter(siret=siret).exists():
            error = _(
                "Une organisation avec ce SIRET existe déjà. Vous devez obtenir une invitation pour la rejoindre."
            )
            raise forms.ValidationError(error)

        # Fetch name and address from API entreprise.
        etablissement = EtablissementAPI(siret)

        if etablissement.error:
            raise forms.ValidationError(etablissement.error)

        # Perform another API call to fetch geocoding data.
        address_fields = [
            etablissement.address_line_1,
            etablissement.address_line_2,
            etablissement.post_code,
            etablissement.city,
            etablissement.department,
        ]
        address_on_one_line = ", ".join([field for field in address_fields if field])
        geocoding_data = get_geocoding_data(address_on_one_line, post_code=etablissement.post_code)

        self.org_data = {
            "siret": siret,
            "name": etablissement.name,
            "address_line_1": etablissement.address_line_1,
            "address_line_2": etablissement.address_line_2,
            "post_code": etablissement.post_code,
            "city": etablissement.city,
            "department": etablissement.department,
            "longitude": geocoding_data["longitude"],
            "latitude": geocoding_data["latitude"],
            "geocoding_score": geocoding_data["score"],
        }

        return siret


class PrescriberPoleEmploiSafirCodeForm(forms.Form):
    """
    Retrieve a PrescriberOrganization from the SAFIR code.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prescriber_organization = None

    safir_code = forms.CharField(
        max_length=5,
        label=gettext_lazy("Code SAFIR"),
        validators=[validate_code_safir],
        help_text=gettext_lazy("Le code SAFIR contient 5 chiffres."),
    )

    def clean_safir_code(self):
        safir_code = self.cleaned_data["safir_code"]
        self.prescriber_organization = PrescriberOrganization.objects.by_safir_code(safir_code)
        if not self.prescriber_organization:
            error = _("Ce code SAFIR est inconnu.")
            raise forms.ValidationError(error)
        return safir_code


class PrescriberPoleEmploiUserSignupForm(FullnameFormMixin, SignupForm):
    """
    Create a new user of type prescriber and add it to the members of the given prescriber organization.
    """

    def __init__(self, *args, **kwargs):
        self.prescriber_organization = kwargs.pop("prescriber_organization")
        super().__init__(*args, **kwargs)
        self.fields["password1"].help_text = CnilCompositionPasswordValidator().get_help_text()
        self.fields["email"].help_text = _("Exemple : nom.prenom@pole-emploi.fr")

    def clean_email(self):
        email = super().clean_email()
        if not email.endswith("@pole-emploi.fr"):
            raise ValidationError(gettext_lazy("L'adresse e-mail doit être une adresse Pôle emploi."))
        return email

    def save(self, request):

        # Create the user.
        user = super().save(request)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_prescriber = True
        user.save()

        # The member becomes a member of the PE agency.
        membership = PrescriberMembership()
        membership.user = user
        membership.organization = self.prescriber_organization
        # The first member becomes an admin.
        membership.is_admin = membership.organization.members.count() == 0
        membership.save()

        # Send a notification to existing members.
        if self.prescriber_organization.active_members.count() > 1:
            self.prescriber_organization.new_signup_warning_email_to_existing_members(user).send()

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
        self.fields["email"].help_text = _("Utilisez une dresse e-mail professionnelle.")

    def save(self, request):

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
            prescriber_org.address_line_1 = self.prescriber_org_data["address_line_1"]
            prescriber_org.address_line_2 = self.prescriber_org_data["address_line_2"] or ""
            prescriber_org.post_code = self.prescriber_org_data["post_code"]
            prescriber_org.city = self.prescriber_org_data["city"]
            prescriber_org.department = self.prescriber_org_data["department"]
            longitude = self.prescriber_org_data["longitude"]
            latitude = self.prescriber_org_data["latitude"]
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
