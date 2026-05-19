from django import forms
from django.urls import reverse_lazy

from itou.files.forms import ItouMultiFileField
from itou.utils.constants import MB


ORIENTATION_FILE_EXTENSIONS = ["doc", "docx", "pdf", "png", "jpeg", "jpg", "odt", "xls", "xlsx", "ods"]
ORIENTATION_FILE_CONTENT_TYPES = ".doc,.docx,.pdf,.png,.jpeg,.jpg,.odt,.xls,.xlsx,.ods"
ORIENTATION_FILE_MAX_SIZE_MB = 5


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
    credentials_documents_files = ItouMultiFileField(
        required=False,
        label="Documents à compléter",
        content_type=ORIENTATION_FILE_CONTENT_TYPES,
        max_upload_size=ORIENTATION_FILE_MAX_SIZE_MB * MB,
        allowed_extensions=ORIENTATION_FILE_EXTENSIONS,
        upload_url=reverse_lazy("insertion_views:safe_upload"),
    )
    credentials_proof_files = ItouMultiFileField(
        required=False,
        label="Pré-requis et justificatifs",
        content_type=ORIENTATION_FILE_CONTENT_TYPES,
        max_upload_size=ORIENTATION_FILE_MAX_SIZE_MB * MB,
        allowed_extensions=ORIENTATION_FILE_EXTENSIONS,
        upload_url=reverse_lazy("insertion_views:safe_upload"),
    )
    gdpr_consent = forms.BooleanField(
        required=True,
        label=(
            "Je consens au traitement de mes données personnelles et de celles du candidat "
            "dans le cadre de cette orientation"
        ),
    )
