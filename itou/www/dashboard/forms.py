from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from itou.siaes.models import Siae


class EditUserInfoForm(forms.ModelForm):
    """
    Edit a user profile.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].input_formats = settings.DATE_INPUT_FORMATS
        if self.instance.is_job_seeker:
            self.fields["birthdate"].required = True
            self.fields["phone"].required = True

    class Meta:
        model = get_user_model()
        fields = ["birthdate", "phone"]
        help_texts = {
            "birthdate": _("Au format jj/mm/aaaa, par exemple 20/12/1978"),
            "phone": _("Par exemple 0610203040"),
        }


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
