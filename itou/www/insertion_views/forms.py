from django import forms
from django.forms import ValidationError
from django_select2.forms import Select2Widget

from itou.files.forms import ItouMultiFileField
from itou.insertion.utils import get_missing_orientation_beneficiary_field_labels
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.constants import MB
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.phone import normalize_phone_number
from itou.utils.templatetags.str_filters import mask_unless


# FIXME(vperron): ensure those files match DORA's allowed file types
ORIENTATION_FILE_EXTENSIONS = ["doc", "docx", "pdf", "png", "jpeg", "jpg", "odt", "xls", "xlsx", "ods"]
ORIENTATION_FILE_CONTENT_TYPES = ".doc,.docx,.pdf,.png,.jpeg,.jpg,.odt,.xls,.xlsx,.ods"
ORIENTATION_FILE_MAX_SIZE_MB = 5


class OrientationSelectJobSeekerForm(forms.Form):
    job_seeker = forms.ChoiceField(
        required=True,
        label="Nom de l'usager",
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom de l'usager",
            }
        ),
    )

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        job_seekers_ids = User.objects.assigned_job_seeker_ids(request.user, request.current_organization)
        job_seeker_qs = (
            User.objects.filter(
                kind=UserKind.JOB_SEEKER,
                pk__in=job_seekers_ids,
                # FIXME: will be fixed when last_name/first_name are enforced by a SQL constraint
                last_name__isnull=False,
                first_name__isnull=False,
            )
            .select_related("jobseeker_profile")
            .order_by("last_name", "first_name")
        )
        self.valid_public_ids = set()
        choices = [("", "---------")]
        for job_seeker in job_seeker_qs:
            self.valid_public_ids.add(str(job_seeker.public_id))
            choices.append(
                (
                    str(job_seeker.public_id),
                    mask_unless(
                        job_seeker.get_inverted_full_name(),
                        predicate=can_view_personal_information(request, job_seeker),
                    ),
                )
            )
        self.fields["job_seeker"].choices = choices

    def clean_job_seeker(self):
        public_id = self.cleaned_data["job_seeker"]
        if public_id not in self.valid_public_ids:
            raise ValidationError("Sélectionnez un usager valide.")
        return public_id


class OrientationConformityForm(forms.Form):
    confirms_conditions = forms.BooleanField(
        required=True,
        label=(
            "Je confirme que l'usager fait partie des publics concernés et que les pré-requis sont respectés. "
            "Je dispose des justificatifs qui me seront demandés à l'étape 3."
        ),
    )

    def __init__(self, job_seeker, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.job_seeker = job_seeker

    def clean(self):
        cleaned_data = super().clean()
        if missing_fields := get_missing_orientation_beneficiary_field_labels(self.job_seeker):
            raise ValidationError(
                "Les informations du candidat sont incomplètes : %(fields)s.",
                params={"fields": ", ".join(missing_fields)},
                code="incomplete_beneficiary",
            )
        return cleaned_data


class OrientationReferentForm(forms.Form):
    referent_last_name = forms.CharField(required=True, label="Nom")
    referent_first_name = forms.CharField(required=True, label="Prénom")
    referent_phone = forms.CharField(
        required=True,
        label="Téléphone",
        help_text="Ex : 0123456789",
        widget=forms.TextInput(attrs={"type": "tel"}),
    )
    referent_email = forms.EmailField(required=True, label="Adresse e-mail", help_text="Ex : mail@domaine.fr")
    orientation_reason = forms.CharField(
        required=False,
        label="Si besoin, détaillez ici le motif de l'orientation",
        help_text=(
            "Merci de ne pas fournir des informations considérées comme sensibles "
            "(situation personnelle ou professionnelle autre que celles cochées à l'étape 1 "
            "de la demande, etc.)."
        ),
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def clean_referent_phone(self):
        phone = self.cleaned_data["referent_phone"]
        if normalized_phone := normalize_phone_number(phone):
            return normalized_phone
        raise ValidationError("Saisissez un numéro de téléphone valide à 10 chiffres.")


class OrientationDocumentsForm(forms.Form):
    credentials_documents_files = ItouMultiFileField(
        required=False,
        label="Documents à compléter",
        content_type=ORIENTATION_FILE_CONTENT_TYPES,
        max_upload_size=ORIENTATION_FILE_MAX_SIZE_MB * MB,
        allowed_extensions=ORIENTATION_FILE_EXTENSIONS,
    )
    credentials_proof_files = ItouMultiFileField(
        required=False,
        label="Pré-requis et justificatifs",
        content_type=ORIENTATION_FILE_CONTENT_TYPES,
        max_upload_size=ORIENTATION_FILE_MAX_SIZE_MB * MB,
        allowed_extensions=ORIENTATION_FILE_EXTENSIONS,
    )
    gdpr_consent = forms.BooleanField(
        required=True,
        label=(
            "Je m'engage en tant qu'accompagnateur, à informer la personne concernée du traitement de ses "
            "données personnelles dans le cadre de cette orientation."
        ),
    )
