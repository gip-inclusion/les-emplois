from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy

from itou.siaes.models import Siae, SiaeMembership
from itou.utils.address.departments import DEPARTMENTS


DEPARTMENTS_CHOICES = [("", "---")] + list(DEPARTMENTS.items())


class CreateSiaeForm(forms.ModelForm):
    """
    Create a new SIAE (Agence / Etablissement in French).
    """

    def __init__(self, current_siae, *args, **kwargs):
        self.current_siae = current_siae
        super().__init__(*args, **kwargs)

        self.fields["department"].choices = DEPARTMENTS_CHOICES

        required_fields = ["address_line_1", "post_code", "city", "department", "phone"]
        for required_field in required_fields:
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
            "brand": gettext_lazy("Si ce champ est renseigné, il sera utilisé en tant que nom sur la fiche."),
            "description": gettext_lazy("Texte de présentation de votre structure."),
            "phone": gettext_lazy("Par exemple 0610203040"),
            "siret": gettext_lazy(
                "Saisissez 14 chiffres. "
                "Doit être le SIRET de votre structure actuelle ou un SIRET avec le même SIREN."
            ),
            "website": gettext_lazy("Votre site web doit commencer par http:// ou https://"),
        }
        error_messages = {
            NON_FIELD_ERRORS: {
                "unique_together": "Il ne peut pas exister plus qu'une %(model_name)s "
                "avec ce %(field_labels)s, or il en existe déjà une."
            }
        }

    def clean_siret(self):
        siret = self.cleaned_data["siret"]
        if not siret.startswith(self.current_siae.siren):
            raise forms.ValidationError(_(f"Le SIRET doit commencer par le SIREN {self.current_siae.siren}"))
        return siret

    def save(self, request, commit=True):
        siae = super().save(commit=commit)
        if commit:
            siae.set_coords(siae.address_on_one_line, post_code=siae.post_code)
            siae.created_by = request.user
            siae.source = Siae.SOURCE_USER_CREATED
            siae.save()
            membership = SiaeMembership()
            membership.user = request.user
            membership.siae = siae
            membership.is_siae_admin = True
            membership.save()
        return siae


class EditSiaeForm(forms.ModelForm):
    """
    Edit an SIAE's card (or "Fiche" in French).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].choices = DEPARTMENTS_CHOICES

        required_fields = ["address_line_1", "post_code", "city", "department"]
        for required_field in required_fields:
            self.fields[required_field].required = True

        # COVID-19 "Operation ETTI".
        # The "description" field is made required for ETTIs during this time.
        if self.instance and (self.instance.kind == self.instance.KIND_ETTI):
            desc_example = _(
                "<p><b>Exemple de description :</b></p>"
                "<p>L'ETTi XXXXX, intervient sur le territoire XXXXX et met à disposition "
                "des intérimaires et notamment pour 5 missions récurrentes :</p>"
                "<ul>"
                "<li>Mission 1</li>"
                "<li>Mission 2</li>"
                "<li>Mission 3</li>"
                "<li>Mission 4</li>"
                "<li>Mission 5</li>"
                "</ul>"
                "<p>Nous sommes disponibles pour étudier avec les entreprises utilisatrices "
                "toutes les missions de premier niveau de qualification."
            )
            self.fields["description"].help_text = mark_safe(desc_example)
            if not self.instance.description:
                self.fields["description"].required = True

    class Meta:
        model = Siae
        fields = [
            "brand",
            "description",
            "phone",
            "email",
            "website",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
        ]
        help_texts = {
            "brand": gettext_lazy("Si ce champ est renseigné, il sera utilisé en tant que nom sur la fiche."),
            "description": gettext_lazy("Texte de présentation de votre structure."),
            "phone": gettext_lazy("Par exemple 0610203040"),
            "website": gettext_lazy("Votre site web doit commencer par http:// ou https://"),
        }

    def save(self, commit=True):
        siae = super().save(commit=commit)
        if commit:
            siae.set_coords(siae.address_on_one_line, post_code=siae.post_code)
            siae.save()
        return siae
