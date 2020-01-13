from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from allauth.account.forms import SignupForm

from itou.prescribers.models import PrescriberOrganization, PrescriberMembership
from itou.siaes.models import Siae, SiaeMembership
from itou.utils.validators import validate_siret


class FullnameFormMixin(forms.Form):

    first_name = forms.CharField(
        label=_("Prénom"),
        max_length=get_user_model()._meta.get_field("first_name").max_length,
        required=True,
        strip=True,
    )

    last_name = forms.CharField(
        label=_("Nom"),
        max_length=get_user_model()._meta.get_field("last_name").max_length,
        required=True,
        strip=True,
    )


class PrescriberSignupForm(FullnameFormMixin, SignupForm):

    secret_code = forms.CharField(
        label=_("Code de l'organisation"),
        max_length=6,
        required=False,
        strip=True,
        help_text=_("Le code est composé de 6 caractères."),
    )

    authorized_organization = forms.ModelChoiceField(
        label=_(
            "Organisation (obligatoire seulement si vous êtes un prescripteur habilité par le Préfet)"
        ),
        queryset=PrescriberOrganization.active_objects.filter(
            is_authorized=True
        ).order_by("name"),
        required=False,
        help_text=_("Liste des prescripteurs habilités par le Préfet."),
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


class SiaeSignupForm(FullnameFormMixin, SignupForm):

    siret = forms.CharField(
        label=_("Numéro SIRET de votre SIAE"),
        max_length=14,
        validators=[validate_siret],
        required=True,
        strip=True,
        help_text=_("Saisissez 14 chiffres."),
    )

    kind = forms.ChoiceField(
        label=_("Type de votre SIAE"), choices=Siae.KIND_CHOICES, required=True
    )

    def clean(self):
        siret = self.cleaned_data.get("siret", None)
        email = self.cleaned_data.get("email", None)
        kind = self.cleaned_data.get("kind", None)

        siret_is_empty = siret is None or siret.strip() == ""
        if siret_is_empty:
            self.raise_validation_error(
                _("Un problème inattendu s'est produit par rapport au champ SIRET.")
            )

        email_is_empty = email is None or email.strip() == ""
        if email_is_empty:
            self.raise_validation_error(
                _("Un problème inattendu s'est produit par rapport au champ email.")
            )

        kind_is_empty = kind is None or kind.strip() == ""
        if kind_is_empty:
            self.raise_validation_error(
                _(
                    "Un problème inattendu s'est produit par rapport au champ type de structure."
                )
            )

        siaes_matching_siret = Siae.active_objects.filter(siret=siret, kind=kind)
        siret_exists = siaes_matching_siret.exists()
        siaes_matching_email = Siae.active_objects.filter(email=email, kind=kind)
        email_exists = siaes_matching_email.exists()
        several_siaes_share_same_email = siaes_matching_email.count() >= 2

        if not siret_exists:

            if several_siaes_share_same_email:
                error_message = _(
                    "Comme plusieurs structures partagent cet email nous nous basons "
                    "sur le SIRET pour identifier votre structure, or "
                    "ce SIRET ne figure pas dans notre base de donnée. "
                )
                self.raise_validation_error(error_message)

            if email_exists:
                return self.cleaned_data

            error_message = _(
                "Ni ce SIRET ni cet email ne figurent dans notre base de données. "
                "Veuillez saisir soit un email connu de l'ASP soit un SIRET connu "
                "de l'ASP."
            )
            self.raise_validation_error(error_message)

        return self.cleaned_data

    def raise_validation_error(self, error_message):
        error_message_suffix = _(
            "Veuillez noter qu'actuellement notre base de données "
            "ne contient que les structures des "
            "territoires d'expérimentation (Pas-de-Calais, Bas-Rhin et Seine Saint Denis).<br>"
            "Contactez-nous si vous rencontrez des problèmes pour vous inscrire : "
            f'<a href="mailto:{settings.ITOU_EMAIL_CONTACT}">{settings.ITOU_EMAIL_CONTACT}</a>'
        )
        # Concatenating two __proxy__ strings is a little tricky.
        error_message = "%s %s" % (error_message, error_message_suffix)
        raise forms.ValidationError(mark_safe(error_message))

    def save(self, request):
        user = super().save(request)

        siae = Siae.active_objects.get(
            siret=self.cleaned_data["siret"], kind=self.cleaned_data["kind"]
        )

        if siae.has_members:
            siae.new_signup_warning_email_to_admins(user).send()
            user.is_active = True
        else:
            user.create_pending_validation()
            siae.new_signup_activation_email_to_official_contact(user).send()
            user.is_active = False

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
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
