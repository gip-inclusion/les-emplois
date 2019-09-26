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
        secret_code = self.cleaned_data.get("secret_code")
        if secret_code:
            membership = PrescriberMembership()
            membership.user = user
            membership.organization = self.organization
            membership.save()

        return user


class SiaeSignupForm(FullnameFormMixin, SignupForm):

    siret = forms.CharField(
        label=_("Numéro SIRET de votre organisation"),
        max_length=14,
        validators=[validate_siret],
        required=True,
        strip=True,
        help_text=_("Saisissez 14 chiffres."),
    )

    def clean_siret(self):
        siret = self.cleaned_data["siret"]
        try:
            Siae.active_objects.get(siret=siret)
        except Siae.DoesNotExist:
            error = _(
                "Ce SIRET ne figure pas dans notre base de données ou ne fait pas partie des "
                "territoires d'expérimentation (Pas-de-Calais, Bas-Rhin et Seine Saint Denis).<br>"
                "Contactez-nous si vous rencontrez des problèmes pour vous inscrire : "
                f'<a href="mailto:{settings.ITOU_EMAIL_CONTACT}">{settings.ITOU_EMAIL_CONTACT}</a>'
            )
            raise forms.ValidationError(mark_safe(error))
        return siret

    def save(self, request):

        user = super().save(request)

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.is_siae_staff = True
        user.save()

        siae = Siae.active_objects.get(siret=self.cleaned_data["siret"])

        membership = SiaeMembership()
        membership.user = user
        membership.siae = siae
        # The first member becomes an admin.
        membership.is_siae_admin = siae.members.count() == 0
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
