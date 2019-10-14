from django import forms
from django.utils.translation import gettext_lazy as _

from itou.siaes.models import Siae


class EditSiaeForm(forms.ModelForm):
    """
    Edit an SIAE's card (or "Fiche" in French).
    """

    accept_data_policy = forms.BooleanField(
        label=_("J'accepte que ces coordonées soient publiques.")
    )

    class Meta:
        model = Siae
        fields = [
            "brand",
            "phone",
            "email",
            "website",
            "description",
            "accept_data_policy",
        ]
        help_texts = {
            "brand": _(
                "Si ce champ est renseigné, il sera utilisé en tant que nom sur la fiche."
            ),
            "phone": _("Par exemple 0610203040"),
            "description": _("Texte de présentation de votre SIAE."),
            "website": _("Votre site web doit commencer par http:// ou https://"),
        }
