from django import forms
from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe

from itou.common_apps.address.departments import DEPARTMENTS
from itou.siaes.models import Siae, SiaeJobDescription, SiaeMembership
from itou.utils.urls import get_external_link_markup


class CreateSiaeForm(forms.ModelForm):
    """
    Create a new SIAE (Agence / Etablissement in French).
    """

    def __init__(self, current_siae, current_user, *args, **kwargs):
        self.current_siae = current_siae
        self.current_user = current_user
        super().__init__(*args, **kwargs)

        self.fields["kind"].choices = [(current_siae.kind, dict(Siae.KIND_CHOICES)[current_siae.kind])]

        self.fields["department"].choices = [("", "---")] + list(DEPARTMENTS.items())

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
            "siret": ("Saisissez 14 chiffres. Doit être un SIRET avec le même SIREN que votre structure actuelle."),
            "kind": "Votre nouvelle structure doit avoir le même type que votre structure actuelle.",
            "brand": "Si ce champ est renseigné, il sera utilisé en tant que nom sur la fiche.",
            "phone": "Par exemple 0610203040",
            "website": "Votre site web doit commencer par http:// ou https://",
            "description": "Texte de présentation de votre structure.",
        }

    def clean_kind(self):
        return self.current_siae.kind

    def clean(self):
        siret = self.cleaned_data.get("siret")
        kind = self.cleaned_data.get("kind")
        existing_siae_query = Siae.objects.filter(siret=siret, kind=kind)

        if existing_siae_query.exists():
            error_message = """
                La structure à laquelle vous souhaitez vous rattacher est déjà
                connue de nos services. Merci de nous contacter à l'adresse
                """
            external_link = get_external_link_markup(
                url=settings.ITOU_ASSISTANCE_URL,
                text=settings.ITOU_ASSISTANCE_URL,
            )
            error_message_siret = (
                "en précisant votre numéro de SIRET (si existant),"
                " le type et l’adresse de cette structure, ainsi que votre numéro de téléphone"
                " pour être contacté(e) si nécessaire."
            )
            error_message = mark_safe(f"{error_message} {external_link} {error_message_siret}")
            raise forms.ValidationError(error_message)

        if not siret.startswith(self.current_siae.siren):
            raise forms.ValidationError(f"Le SIRET doit commencer par le SIREN {self.current_siae.siren}")

        return self.cleaned_data

    def save(self, request):
        siae = super().save(commit=False)
        siae.set_coords(siae.geocoding_address, post_code=siae.post_code)
        siae.created_by = request.user
        siae.source = Siae.SOURCE_USER_CREATED
        siae.convention = self.current_siae.convention
        siae.save()

        SiaeMembership.objects.create(siae=siae, is_admin=True, user=request.user)

        return siae


class EditSiaeForm(forms.ModelForm):
    """
    Edit an SIAE's card (or "Fiche" in French).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].choices = [("", "---")] + list(DEPARTMENTS.items())

        required_fields = ["address_line_1", "post_code", "city", "department"]
        for required_field in required_fields:
            self.fields[required_field].required = True

        # COVID-19 "Operation ETTI".
        # The "description" field is made required for ETTIs during this time.
        if self.instance and (self.instance.kind == self.instance.KIND_ETTI):
            desc_example = (
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
            "brand": (
                "Si ce champ est renseigné, il sera utilisé en tant que nom "
                "sur la fiche et dans les résultats de recherche."
            ),
            "description": "Texte de présentation de votre structure.",
            "phone": "Par exemple 0610203040",
            "website": "Votre site web doit commencer par http:// ou https://",
        }

    def save(self):
        siae = super().save(commit=False)
        siae.set_coords(siae.geocoding_address, post_code=siae.post_code)
        siae.save()
        return siae


class BlockJobApplicationsForm(forms.ModelForm):
    """
    Toggle blocking new job applications for this SIAE (used in dashboard settings)
    """

    class Meta:
        model = Siae
        fields = ["block_job_applications"]
        labels = {"block_job_applications": "Ne plus recevoir de nouvelles candidatures"}

    def save(self, commit=True):
        siae = super().save(commit=commit)
        block_job_applications = self.cleaned_data["block_job_applications"]

        if commit:
            if block_job_applications:
                siae.job_applications_blocked_at = timezone.now()
            siae.block_job_applications = block_job_applications
            siae.save()
        return siae


class FinancialAnnexSelectForm(forms.Form):
    """
    Select a financial annex matching the same SIREN and kind as the convention of the current siae.
    """

    def __init__(self, *args, **kwargs):
        self.financial_annexes = kwargs.pop("financial_annexes")
        super().__init__(*args, **kwargs)
        self.fields["financial_annexes"].queryset = self.financial_annexes
        self.fields["financial_annexes"].label_from_instance = self.label_from_instance

    @staticmethod
    def label_from_instance(self):
        """
        Display a custom value for the AF in the dropdown instead of the default af.__str__.

        From https://stackoverflow.com/questions/41969899/display-field-other-than-str
        """
        return self.number_prefix_with_spaces

    financial_annexes = forms.ModelChoiceField(
        label="Numéro d'annexe financière sans son suffixe de type 'A1M1'",
        queryset=None,
        widget=forms.Select,
        help_text="Veuillez sélectionner un numéro existant.",
    )


class ValidateSiaeJobDescriptionForm(forms.ModelForm):
    """
    Validate a job description.
    """

    class Meta:
        model = SiaeJobDescription
        fields = [
            "custom_name",
            "description",
            "is_active",
            "is_displayed",
        ]
