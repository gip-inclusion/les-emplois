from django import forms
from django.utils.translation import gettext_lazy as _

from itou.siaes.models import Siae


class EditSiaeForm(forms.ModelForm):
    """
    Edit an SIAE's card (or "Fiche" in French).
    """

    class Meta:
        model = Siae
        fields = ["brand", "phone", "email", "website", "description"]
        help_texts = {
            "brand": _(
                "Si ce champ est renseigné, il sera utilisé en tant que nom sur la fiche."
            ),
            "phone": _("Par exemple 0610203040"),
            "description": _("Texte de présentation de votre SIAE."),
        }
