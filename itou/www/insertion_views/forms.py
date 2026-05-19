from django import forms
from django.core.validators import FileExtensionValidator
from django.utils.formats import localize

from itou.files.forms import ItouFileInput
from itou.utils.constants import MB


ORIENTATION_FILE_EXTENSIONS = ["doc", "docx", "pdf", "png", "jpeg", "jpg", "odt", "xls", "xlsx", "ods"]
ORIENTATION_FILE_CONTENT_TYPES = ".doc,.docx,.pdf,.png,.jpeg,.jpg,.odt,.xls,.xlsx,.ods"
ORIENTATION_FILE_MAX_SIZE_MB = 5


def _orientation_file_field(**kwargs: object) -> forms.FileField:
    return forms.FileField(
        widget=ItouFileInput(
            content_type=ORIENTATION_FILE_CONTENT_TYPES,
            max_upload_size_mb=ORIENTATION_FILE_MAX_SIZE_MB,
        ),
        validators=[FileExtensionValidator(ORIENTATION_FILE_EXTENSIONS)],
        **kwargs,
    )


class OrientationConformityForm(forms.Form):
    confirms_conditions = forms.BooleanField(
        required=True,
        label="Je confirme que le candidat répond aux critères d'éligibilité du service",
    )


class OrientationReferentForm(forms.Form):
    referent_last_name = forms.CharField(required=True, label="Nom")
    referent_first_name = forms.CharField(required=True, label="Prénom")
    referent_phone = forms.CharField(
        required=True,
        label="Téléphone",
        widget=forms.TextInput(attrs={"type": "tel"}),
    )
    referent_email = forms.EmailField(required=True, label="Email")
    orientation_reason = forms.CharField(
        required=False,
        label="Motif de l'orientation",
        widget=forms.Textarea,
    )


class OrientationDocumentsForm(forms.Form):
    credentials_documents_files = _orientation_file_field(
        required=False,
        label="Documents à compléter",
    )
    credentials_proof_files = _orientation_file_field(
        required=False,
        label="Pré-requis et justificatifs",
    )
    gdpr_consent = forms.BooleanField(
        required=True,
        label=(
            "Je consens au traitement de mes données personnelles et de celles du candidat "
            "dans le cadre de cette orientation"
        ),
    )

    def clean(self) -> dict:
        cleaned_data = super().clean()
        max_size = ORIENTATION_FILE_MAX_SIZE_MB * MB
        for field_name in ("credentials_documents_files", "credentials_proof_files"):
            file = cleaned_data.get(field_name)
            if file and file.size > max_size:
                self.add_error(
                    field_name,
                    forms.ValidationError(
                        f"Le fichier doit faire moins de {localize(ORIENTATION_FILE_MAX_SIZE_MB)} Mo."
                    ),
                )
        return cleaned_data
