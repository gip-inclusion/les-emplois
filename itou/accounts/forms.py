from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from allauth.account.forms import SignupForm

from itou.prescribers.models import Prescriber, PrescriberMembership
from itou.siae.models import Siae, SiaeMembership
from itou.utils.geocoding import get_geocoding_data
from itou.utils.siret import get_siret_data
from itou.utils.validators import validate_siret


class FullnameFormMixin(forms.Form):

    first_name = forms.CharField(
        label=_("Prénom"),
        max_length=get_user_model()._meta.get_field('first_name').max_length,
        required=True,
        strip=True,
    )

    last_name = forms.CharField(
        label=_("Nom"),
        max_length=get_user_model()._meta.get_field('last_name').max_length,
        required=True,
        strip=True,
    )


class SiretFormMixin(forms.Form):

    siret = forms.CharField(
        label=_("Numéro SIRET de votre organisation"),
        max_length=14,
        validators=[validate_siret],
        required=True,
        strip=True,
        help_text=_("Le numéro SIRET doit être composé de 14 chiffres."),
    )


class PrescriberSignupForm(FullnameFormMixin, SiretFormMixin, SignupForm):

    def save(self, request):

        user = super().save(request)

        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.is_prescriber = True
        user.save()

        prescriber, is_new = Prescriber.objects.get_or_create(siret=self.cleaned_data['siret'])
        # Try to automatically gather information for the given SIRET.
        # The user will have the possibility to modify or complete information later.
        siret_data = get_siret_data(self.cleaned_data['siret'])
        if siret_data:
            prescriber.name = siret_data['name']
            prescriber.geocode(siret_data['address'], siret_data['zipcode'], save=False)
        prescriber.save()

        membership = PrescriberMembership()
        membership.user = user
        membership.prescriber = prescriber
        # The first member becomes an admin.
        membership.is_prescriber_admin = is_new
        membership.save()

        return user


class SiaeSignupForm(FullnameFormMixin, SiretFormMixin, SignupForm):

    def clean_siret(self):
        siret = self.cleaned_data['siret']
        try:
            siae = Siae.active_objects.get(siret=siret)
        except Siae.DoesNotExist:
            error = _(
                "Ce SIRET ne figure pas dans notre base de données ou ne fait pas partie des "
                "territoires d'expérimentation (Pas-de-Calais, Bas-Rhin et Seine Saint Denis).<br>"
                "Contactez-nous si vous rencontrez des problèmes pour vous inscrire : "
                f"<a href=\"mailto:{settings.ITOU_EMAIL_CONTACT}\">{settings.ITOU_EMAIL_CONTACT}</a>"
            )
            raise forms.ValidationError(mark_safe(error))
        return siret

    def save(self, request):

        user = super().save(request)

        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.is_siae_staff = True
        user.save()

        siae = Siae.active_objects.get(siret=self.cleaned_data['siret'])

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

        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.is_job_seeker = True
        user.save()

        return user
