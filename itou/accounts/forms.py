from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from allauth.account.forms import SignupForm

from itou.prescribers.models import Prescriber, PrescriberMembership
from itou.utils.geocoding import get_geocoding_data
from itou.utils.siret import get_siret_data
from itou.utils.validators import validate_siret


class PrescriberSignupForm(SignupForm):

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
    siret = forms.CharField(
        label=_("Numéro SIRET de votre organisation"),
        max_length=14,
        validators=[validate_siret],
        required=True,
        strip=True,
        help_text=_("Le numéro SIRET doit être composé de 14 chiffres."),
    )

    def save(self, request):

        user = super().save(request)

        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.save()

        prescriber, is_new = Prescriber.objects.get_or_create(siret=self.cleaned_data['siret'])
        prescriber.save()

        membership = PrescriberMembership()
        membership.user = user
        membership.prescriber = prescriber
        # The first `user` who creates a `prescriber` becomes an admin.
        membership.is_prescriber_admin = is_new
        membership.save()

        # Try to automatically gather information for the given SIRET.
        # The user will have the possibility to modify the information later.
        siret_data = get_siret_data(self.cleaned_data['siret'])
        if siret_data:
            prescriber.name = siret_data['name']

            geocoding_data = get_geocoding_data(siret_data['address'], zipcode=siret_data['zipcode'])
            if geocoding_data:
                prescriber.address_line_1 = geocoding_data['address_line_1']
                prescriber.zipcode = siret_data['zipcode']
                prescriber.city = geocoding_data['city']
                prescriber.coords = geocoding_data['coords']
                prescriber.geocoding_score = geocoding_data['score']

            prescriber.save()

        return user
