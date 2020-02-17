from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
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


class SelectSiaeForm(forms.ModelForm):
    """
    First of two forms of siae signup process.
    This first form allows the user to select which siae will be joined.
    """

    class Meta:
        model = Siae
        fields = ["kind", "siret", "email"]

    kind = forms.ChoiceField(
        label=gettext_lazy("Type de votre structure"),
        choices=BLANK_CHOICE + Siae.KIND_CHOICES,
        required=True,
    )

    siret = forms.CharField(
        label=gettext_lazy("Numéro SIRET de votre structure"),
        min_length=14,
        max_length=14,
        validators=[validate_siret],
        strip=True,
        help_text=gettext_lazy(
            "Saisissez 14 chiffres. Doit si possible être le SIRET connu de l'ASP pour les SIAE."
        ),
        required=False,
    )

    email = forms.EmailField(
        label=gettext_lazy("E-mail"),
        help_text=gettext_lazy("Doit si possible être l'adresse e-mail connue de l'ASP pour les SIAE."),
        required=False,
    )

    def save(self, request, commit=True):
        raise RuntimeError("SelectSiaeForm.save() should never be called.")

    # pylint: disable=inconsistent-return-statements
    def clean(self):
        kind = self.cleaned_data["kind"]
        siret = self.cleaned_data["siret"]
        email = self.cleaned_data["email"]

        if not (siret or email):
            error_message = _(
                "Veuillez saisir soit un email connu de l'ASP soit un SIRET connu "
                "de l'ASP."
            )
            self.raise_validation_error(error_message, add_suffix=False)

        if siret:
            siaes_matching_siret = Siae.active_objects.filter(siret=siret, kind=kind)
            siret_exists = siaes_matching_siret.exists()
        else:
            siret_exists = False

        if siret_exists:
            return self.cleaned_data

        if email:
            siaes_matching_email = Siae.active_objects.filter(
                auth_email=email, kind=kind
            )
            email_exists = siaes_matching_email.exists()
            several_siaes_share_same_email = siaes_matching_email.count() > 1
        else:
            email_exists = False
            several_siaes_share_same_email = False

        if several_siaes_share_same_email:
            error_message = _(
                "Comme plusieurs structures partagent cet email nous nous basons "
                "sur le SIRET pour identifier votre structure, or "
                "ce SIRET ne figure pas dans notre base de données.<br>"
                "Veuillez saisir un SIRET connu de l'ASP."
            )
            self.raise_validation_error(error_message)

        if email_exists:
            return self.cleaned_data

        error_message = _(
            "Ni ce SIRET ni cet email ne figurent dans notre base de données "
            "pour ce type de SIAE.<br>"
            "Veuillez saisir le type correct de votre SIAE et soit un email connu de l'ASP "
            "soit un SIRET connu de l'ASP.<br>"
            "Si nécéssaire veuillez vous rapprocher de votre service gestion "
            "pour obtenir ces informations."
        )
        self.raise_validation_error(error_message)

    def raise_validation_error(self, error_message, add_suffix=True):
        error_message_suffix = _(
            "Contactez-nous si vous rencontrez des problèmes pour vous inscrire : "
            f'<a href="mailto:{settings.ITOU_EMAIL_CONTACT}">{settings.ITOU_EMAIL_CONTACT}</a>'
        )
        if add_suffix:
            # Concatenating two __proxy__ strings is a little tricky.
            error_message = "%s<br>%s" % (error_message, error_message_suffix)
        raise forms.ValidationError(mark_safe(error_message))


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
