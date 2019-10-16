from django import forms
from django.utils.translation import gettext_lazy as _

from itou.prescribers.models import PrescriberOrganization
from itou.utils.apis.siret import get_siret_data
from itou.prescribers.models import PrescriberMembership


class CreatePrescriberOrganizationForm(forms.ModelForm):
    """
    Create a prescriber organization.
    """

    class Meta:
        model = PrescriberOrganization
        fields = ["name", "siret", "phone", "email", "website", "description"]
        help_texts = {
            "siret": _("Le numéro SIRET doit être composé de 14 chiffres."),
            "phone": _("Par exemple 0610203040"),
            "description": _("Texte de présentation de votre organisation."),
            "website": _("Votre site web doit commencer par http:// ou https://"),
        }

    def save(self, user, commit=True):
        organization = super().save(commit=False)

        siret = self.cleaned_data["siret"]
        if siret:
            siret_data = get_siret_data(self.cleaned_data["siret"])
            # Try to automatically gather information for the given SIRET.
            if siret_data:
                organization.geocode(
                    siret_data["address"], post_code=siret_data["post_code"], save=False
                )
                organization.siret = siret

        if commit:
            organization.save()
            membership = PrescriberMembership()
            membership.user = user
            membership.organization = organization
            membership.is_admin = True
            membership.save()
        return organization


class EditPrescriberOrganizationForm(forms.ModelForm):
    """
    Edit a prescriber organization.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_authorized:
            # Do not edit the name of an authorized prescriber organization.
            del self.fields["name"]

    class Meta:
        model = PrescriberOrganization
        fields = ["name", "phone", "email", "website", "description"]
        help_texts = {
            "phone": _("Par exemple 0610203040"),
            "description": _("Texte de présentation de votre SIAE."),
            "website": _("Votre site web doit commencer par http:// ou https://"),
        }
