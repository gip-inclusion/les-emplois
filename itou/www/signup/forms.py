from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse_lazy
from django.utils.http import urlsafe_base64_decode
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy

from allauth.account.forms import SignupForm
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.siaes.models import Siae, SiaeMembership
from itou.utils.address.forms import AddressFormMixin
from itou.utils.tokens import siae_signup_token_generator
from itou.utils.validators import validate_siret


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


class PrescriberMixin(FullnameFormMixin, SignupForm):
    secret_code = forms.CharField(
        label=gettext_lazy("Code de l'organisation"),
        max_length=6,
        required=False,
        strip=True,
        help_text=gettext_lazy("Le code est composé de 6 caractères."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = None

    def clean_secret_code(self):
        """
        Retrieve a PrescriberOrganization instance from the `secret_code` field.
        """
        secret_code = self.cleaned_data["secret_code"]
        if secret_code:
            secret_code = secret_code.upper()
            try:
                self.organization = PrescriberOrganization.objects.get(secret_code=secret_code)
            except PrescriberOrganization.DoesNotExist:
                error = _("Ce code n'est pas valide.")
                raise forms.ValidationError(error)
        return secret_code

    def save(self, request):
        user = super().save(request)

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_prescriber = True
        user.save()

        # Join organization.
        organization = self.organization  # or authorized_organization
        if organization:
            if organization.has_members:
                organization.new_signup_warning_email_to_existing_members(user).send()
            membership = PrescriberMembership()
            membership.user = user
            membership.organization = organization
            # The first member becomes an admin.
            membership.is_admin = membership.organization.members.count() == 0
            membership.save()

        return user


class OrienterPrescriberForm(PrescriberMixin):
    secret_code = forms.CharField(
        label=gettext_lazy("Vous avez un code d'organisation? Entrez le code qui vous a été transmis"),
        widget=forms.TextInput(attrs={"placeholder": gettext_lazy("Code d'organisation")}),
        max_length=6,
        required=False,
        strip=True,
        help_text=gettext_lazy("Le code est composé de 6 caractères."),
    )


class PoleEmploiPrescriberForm(PrescriberMixin):
    safir_code = forms.CharField(max_length=5, label=gettext_lazy("Code SAFIR"))

    def clean_email(self):
        email = self.cleaned_data["email"]
        if not email.endswith("@pole-emploi.fr"):
            raise ValidationError(gettext_lazy("L'adresse email doit etre une adresse Pole-Emploi"))
        return email

    def clean_safir_code(self):
        safir_code = self.cleaned_data["safir_code"]
        self.organization = PrescriberOrganization.by_safir_code(safir_code)
        if not self.organization:
            raise ValidationError(gettext_lazy("Ce code SAFIR est inconnu"))
        return safir_code


class AuthorizedPrescriberForm(PrescriberMixin):

    PRESCRIBER_ORGANIZATION_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:prescribers_organizations")

    authorized_organization_id = forms.CharField(
        required=False, widget=forms.HiddenInput(attrs={"class": "js-prescriber-organization-autocomplete-hidden"})
    )

    authorized_organization = forms.CharField(
        label=gettext_lazy("Si vous êtes un prescripteur habilité par le Préfet, saisissez votre organisation"),
        required=False,
        help_text=gettext_lazy("Liste des prescripteurs habilités par le Préfet."),
        widget=forms.TextInput(
            attrs={
                "class": "js-prescriber-organization-autocomplete-input form-control",
                "data-autocomplete-source-url": PRESCRIBER_ORGANIZATION_AUTOCOMPLETE_SOURCE_URL,
                "placeholder": gettext_lazy("Saisissez une organisation"),
                "autocomplete": "off",
            }
        ),
    )

    unregistered_organization = forms.CharField(
        label=gettext_lazy(
            "Si vous faites partie d'une organisation habilitée par le Préfet qui ne figure pas dans la liste, "
            "saisissez son nom dans le bloc ci-dessous"
        ),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": gettext_lazy("Saisissez le nom d'une organisation habilitée")}),
    )

    def clean(self):
        """
        User must enter one of:
        * an unregistered organization
        * a registered one in the auto-complete list
        Not both or none
        """
        unregistered_organization = self.cleaned_data["unregistered_organization"]
        authorized_organization_id = self.cleaned_data["authorized_organization_id"]

        if (unregistered_organization and authorized_organization_id) or not (
            unregistered_organization or authorized_organization_id
        ):
            raise ValidationError(
                gettext_lazy(
                    "Vous devez choisir entre une organisation déjà habilitée "
                    "et une organisation habilitée à valider ultérieurement"
                )
            )

        if unregistered_organization:
            # check if exists ?
            if PrescriberOrganization.objects.filter(name=unregistered_organization.strip()).exists():
                raise ValidationError(
                    gettext_lazy(
                        f"Cette organisation existe ({unregistered_organization})."
                        "Veuillez la sélectionner dans la liste des organisations habilitées"
                    )
                )
            new_organization = PrescriberOrganization(name=unregistered_organization)
            new_organization.is_validated = False
            new_organization.save()
            self.organization = new_organization
        elif authorized_organization_id:
            authorized_organization = PrescriberOrganization.objects.get(
                pk=self.cleaned_data["authorized_organization_id"]
            )
            if not authorized_organization:
                raise ValidationError(
                    gettext_lazy(
                        f"Impossible de trouver cette organisation (id: {authorized_organization_id}). "
                        "Veuillez contacter le support"
                    )
                )
            self.organization = authorized_organization


class SelectSiaeForm(forms.Form):
    """
    First of two forms of siae signup process.
    This first form allows the user to select which siae will be joined.
    """

    kind = forms.ChoiceField(
        label=gettext_lazy("Type de structure"), choices=BLANK_CHOICE + Siae.KIND_CHOICES, required=True
    )

    siret = forms.CharField(
        label=gettext_lazy("Numéro de SIRET"),
        min_length=14,
        max_length=14,
        validators=[validate_siret],
        strip=True,
        help_text=gettext_lazy(
            "Saisissez 14 chiffres. Numéro connu possiblement de l'Agence de services et de paiement (ASP)"
        ),
        required=False,
    )

    email = forms.EmailField(
        label=gettext_lazy("E-mail"),
        help_text=gettext_lazy(
            "Pour les SIAE, adresse e-mail connue possiblement de l'Agence de services et de paiement (ASP)"
        ),
        required=False,
    )

    def clean(self):
        cleaned_data = super().clean()
        kind = cleaned_data.get("kind")
        siret = cleaned_data.get("siret")
        email = cleaned_data.get("email")

        if not (siret or email):
            error_message = _("Merci de renseigner un e-mail ou un numéro de SIRET connu de nos services.")
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

        if siret_exists:
            self.selected_siae = siaes_matching_siret[0]
        else:
            siaes_matching_email = [s for s in siaes if s.auth_email == email]
            email_exists = len(siaes_matching_email) > 0
            several_siaes_share_same_email = len(siaes_matching_email) > 1

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
                    f"Votre numéro de SIRET ou votre e-mail nous sont inconnus.<br>"
                    f"Merci de vérifier votre saisie ou veuillez nous contacter "
                    f"à l'adresse suivante : {settings.ITOU_EMAIL_CONTACT}"
                )
                raise forms.ValidationError(mark_safe(error_message))

            self.selected_siae = siaes_matching_email[0]


class SiaeSignupForm(FullnameFormMixin, SignupForm):
    """
    Second of two forms of siae signup process.
    This is the final form where the signup actually happens
    on the siae identified by the first form.
    """

    def __init__(self, *args, **kwargs):
        super(SiaeSignupForm, self).__init__(*args, **kwargs)
        self.fields["kind"].widget.attrs["readonly"] = True
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
            raise RuntimeError("This should never happen. Attack attempted.")

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
        siae = Siae.objects.get(pk=siae_id)
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


class JobSeekerSignupForm(FullnameFormMixin, SignupForm, AddressFormMixin):
    def save(self, request):
        user = super().save(request)

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]

        # Optional address part
        user.address_line_1 = self.cleaned_data["address_line_1"]
        user.address_line_2 = self.cleaned_data["address_line_2"]
        user.post_code = self.cleaned_data["post_code"]
        user.city = self.cleaned_data["city"]

        user.is_job_seeker = True
        user.save()

        return user
