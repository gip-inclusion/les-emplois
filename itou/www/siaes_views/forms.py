from django import forms
from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy

from itou.siaes.models import Siae, SiaeMembership
from itou.utils.address.departments import DEPARTMENTS


DEPARTMENTS_CHOICES = [("", "---")] + list(DEPARTMENTS.items())


class CreateSiaeForm(forms.ModelForm):
    """
    Create a new SIAE (Agence / Etablissement in French).
    """

    def __init__(self, current_siae, current_user, *args, **kwargs):
        self.current_siae = current_siae
        self.current_user = current_user
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

    def clean(self):
        siret = self.cleaned_data["siret"]
        kind = self.cleaned_data["kind"]
        existing_siae_query = Siae.objects.filter(siret=siret, kind=kind)

        if existing_siae_query.exists():
            existing_siae = existing_siae_query.get()
            user = self.current_user
            error_message = _(
                """
                La structure à laquelle vous souhaitez vous rattacher est déjà
                connue de nos services. Merci de nous contacter à l'adresse
                """
            )

            error_message_siret = _(
                "en précisant votre numéro de SIRET (si existant),"
                " le type et l’adresse de cette structure, ainsi que votre numéro de téléphone"
                " pour être contacté(e) si nécessaire."
            )
            mail_to = settings.ITOU_EMAIL_ASSISTANCE
            mail_subject = _("Se rattacher à une structure existante - Plateforme de l'inclusion")

            mail_body = _(
                "Veuillez rattacher mon compte (%(first_name)s %(last_name)s %(email)s)"
                " à la structure existante (%(kind)s %(siret)s ID=%(id)s)"
                " sur la Plateforme de l'inclusion."
            ) % {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "kind": existing_siae.kind,
                "siret": existing_siae.siret,
                "id": existing_siae.id,
            }

            mailto_html = (
                f'<a href="mailto:{mail_to}?subject={mail_subject}&body={mail_body}"'
                f' target="_blank" class="alert-link">{mail_to}</a>'
            )
            error_message = mark_safe(f"{error_message} {mailto_html} {error_message_siret}")
            raise forms.ValidationError(error_message)

        if not siret.startswith(self.current_siae.siren):
            raise forms.ValidationError(_(f"Le SIRET doit commencer par le SIREN {self.current_siae.siren}"))

        return self.cleaned_data

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


class BlockJobApplicationsForm(forms.ModelForm):
    """
    Toggle blocking new job applications for this SIAE (used in dashboard settings)
    """

    class Meta:
        model = Siae
        fields = ["block_job_applications"]
        labels = {"block_job_applications": gettext_lazy("Ne plus recevoir de nouvelles candidatures")}

    def save(self, commit=True):
        siae = super().save(commit=commit)
        block_job_applications = self.cleaned_data["block_job_applications"]

        if commit:
            if block_job_applications:
                siae.job_applications_blocked_at = timezone.now()
            siae.block_job_applications = block_job_applications
            siae.save()
        return siae
