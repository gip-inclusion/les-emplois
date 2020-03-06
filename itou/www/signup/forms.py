from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy

from allauth.account.forms import SignupForm

from itou.prescribers.models import PrescriberOrganization, PrescriberMembership
from itou.siaes.models import Siae, SiaeMembership
from itou.utils.validators import validate_siret
from itou.www.signup import utils


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


class PrescriberSignupForm(FullnameFormMixin, SignupForm):

    secret_code = forms.CharField(
        label=gettext_lazy("Code de l'organisation"),
        max_length=6,
        required=False,
        strip=True,
        help_text=gettext_lazy("Le code est composé de 6 caractères."),
    )

    authorized_organization = forms.ModelChoiceField(
        label=gettext_lazy(
            "Organisation (obligatoire seulement si vous êtes un prescripteur habilité par le Préfet)"
        ),
        queryset=PrescriberOrganization.active_objects.filter(
            is_authorized=True
        ).order_by("name"),
        required=False,
        help_text=gettext_lazy("Liste des prescripteurs habilités par le Préfet."),
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
                self.organization = PrescriberOrganization.objects.get(
                    secret_code=secret_code
                )
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
        authorized_organization = self.cleaned_data["authorized_organization"]
        if authorized_organization or self.organization:
            membership = PrescriberMembership()
            membership.user = user
            membership.organization = self.organization or authorized_organization
            # The first member becomes an admin.
            membership.is_admin = membership.organization.members.count() == 0
            membership.save()

        return user


class SelectSiaeForm(forms.Form):
    """
    First of two forms of siae signup process.
    This first form allows the user to select which siae will be joined.
    """

    kind = forms.ChoiceField(
        label=gettext_lazy("Type de structure"),
        choices=BLANK_CHOICE + Siae.KIND_CHOICES,
        required=True,
    )

    siret = forms.CharField(
        label=gettext_lazy("Numéro de SIRET"),
        min_length=14,
        max_length=14,
        validators=[validate_siret],
        strip=True,
        help_text=gettext_lazy(
            "Saisissez 14 chiffres. Numéro connue possiblement de l'Agence de services et de paiement (ASP)"
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
            error_message = _(
                "Merci de renseigner un e-mail ou un numéro de SIRET connu de nos services."
            )
            raise forms.ValidationError(mark_safe(error_message))

        siaes = Siae.active_objects.filter(kind=kind)
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
                    "Votre numéro de SIRET ou votre e-mail nous sont inconnus.<br>"
                    "Merci de vérifier votre saisie ou veuillez nous contacter à l'adresse suivante : contact@inclusion.beta.gouv.fr<br>"
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

    def save(self, request):
        user = super().save(request)

        if utils.check_siae_signup_credentials(request.session):
            siae = utils.get_siae_from_session(request.session)
        else:
            raise RuntimeError("This should never happen. Attack attempted.")

        if siae.has_members:
            siae.new_signup_warning_email_to_admins(user).send()

        user.is_siae_staff = True
        user.save()

        membership = SiaeMembership()
        membership.user = user
        membership.siae = siae
        # Only the first member becomes an admin.
        membership.is_siae_admin = siae.active_members.count() == 0
        membership.save()

        return user


class JobSeekerSignupForm(FullnameFormMixin, SignupForm):
    def save(self, request):

        user = super().save(request)

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_job_seeker = True
        user.save()

        return user
