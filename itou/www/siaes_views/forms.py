from functools import partial

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from itou.siaes.models import Siae, SiaeMembership
from itou.utils.address.departments import DEPARTMENTS
from itou.utils.validators import (
    validate_siret,
    validate_siren_matches_siret,
    validate_post_code,
)


class CreateSiaeForm(forms.ModelForm):
    """
    Create a new SIAE (Agence / Etablissement in French).
    """

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super(CreateSiaeForm, self).__init__(*args, **kwargs)

        self.fields.get("siret").initial = self.get_current_siae().siret

        validate_siret_matches_current_siren = partial(
            validate_siren_matches_siret, self.get_current_siae().siren
        )

        self.fields.get("siret").validators = [
            validate_siret,
            validate_siret_matches_current_siren,
        ]

        test_departments = {d: DEPARTMENTS[d] for d in settings.ITOU_TEST_DEPARTMENTS}
        self.fields.get("department").choices = test_departments.items()

        required_fields = ["address_line_1", "city", "department", "phone"]
        for required_field in required_fields:
            # Make field required without overwriting its other properties.
            self.fields[required_field].required = True

    class Meta:
        model = Siae
        fields = [
            "siret",
            "kind",
            "name",
            "brand",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
            "phone",
            "email",
            "website",
            "description",
        ]
        help_texts = {
            "brand": _(
                "Si ce champ est renseigné, il sera utilisé en tant que nom sur la fiche."
            ),
            "department": _(
                (
                    "Seulement les départements du Bas-Rhin (67), du Pas-de-Calais (62) "
                    + "et de la Seine Saint Denis (93) sont disponibles pendant la phase actuelle "
                    + "d'expérimentation de la plateforme de l'inclusion."
                )
            ),
            "phone": _("Par exemple 0610203040"),
            "website": _("Votre site web doit commencer par http:// ou https://"),
            "description": _("Texte de présentation de votre SIAE."),
        }

    siret = forms.CharField(
        label=_("Numéro SIRET"),
        min_length=14,
        max_length=14,
        required=True,
        strip=True,
        help_text=_(
            "Saisissez 14 chiffres. Doit être le SIRET de votre structure actuelle ou un SIRET avec le même SIREN."
        ),
    )

    post_code = forms.CharField(
        label=_("Code Postal"),
        min_length=5,
        max_length=5,
        validators=[validate_post_code],
        required=True,
        strip=True,
        help_text=_("Saisissez les 5 chiffres de votre code postal."),
    )

    def save(self, request):

        siae = super().save(request)
        siae.geocode(
            f"{siae.address_line_1} {siae.address_line_2}",
            post_code=siae.post_code,
            save=False,
        )
        siae.is_from_asp = False
        siae.save()

        membership = SiaeMembership()
        membership.user = request.user
        membership.siae = siae
        membership.is_siae_admin = True
        membership.save()

        return siae

    def get_current_siae(self):
        current_siae_pk = self.request.session.get(
            settings.ITOU_SESSION_CURRENT_SIAE_KEY
        )
        current_siae = self.request.user.siae_set.get(pk=current_siae_pk)
        return current_siae


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
            "website": _("Votre site web doit commencer par http:// ou https://"),
        }
