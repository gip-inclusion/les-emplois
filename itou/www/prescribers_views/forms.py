from django import forms
from django.utils.translation import gettext_lazy

from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.utils.apis.siret import get_siret_data


class CreatePrescriberOrganizationForm(forms.ModelForm):
    """
    Create a prescriber organization.
    """

    class Meta:
        model = PrescriberOrganization
        fields = ["name", "siret", "phone", "email", "website", "description"]
        help_texts = {
            "siret": gettext_lazy("Le numéro SIRET doit être composé de 14 chiffres."),
            "phone": gettext_lazy("Par exemple 0610203040"),
            "description": gettext_lazy("Texte de présentation de votre organisation."),
            "website": gettext_lazy(
                "Votre site web doit commencer par http:// ou https://"
            ),
        }

    def save(self, user, commit=True):
        organization = super().save(commit=False)

        siret = self.cleaned_data["siret"]
        if siret:
            siret_data = get_siret_data(self.cleaned_data["siret"])
            # Try to automatically gather information for the given SIRET.
            if siret_data:
                organization.set_coords_and_address(
                    siret_data["address"], post_code=siret_data["post_code"]
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
            "phone": gettext_lazy("Par exemple 0610203040"),
            "description": gettext_lazy("Texte de présentation de votre structure."),
            "website": gettext_lazy(
                "Votre site web doit commencer par http:// ou https://"
            ),
        }
