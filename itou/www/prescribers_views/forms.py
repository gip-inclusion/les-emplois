from django import forms
from django.utils.translation import gettext_lazy

from itou.prescribers.models import PrescriberOrganization


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
            "website": gettext_lazy("Votre site web doit commencer par http:// ou https://"),
        }
