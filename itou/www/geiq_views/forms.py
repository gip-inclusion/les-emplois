from django import forms

from itou.files.forms import ItouFileField
from itou.geiq.models import ImplementationAssessment, ReviewState
from itou.utils.constants import MB


class AssessmentSubmissionForm(forms.Form):
    activity_report_file = ItouFileField(
        content_type="application/pdf",
        max_upload_size=5 * MB,
        label="Importer un fichier",
    )
    up_to_date_information = forms.BooleanField(
        required=True,
        label="En cochant cette case, je certifie que les données de l’année concernée sont à jour.",
    )


class AssessmentReviewForm(forms.ModelForm):
    class Meta:
        model = ImplementationAssessment
        fields = (
            "review_state",
            "review_comment",
        )
        help_texts = {
            "review_comment": "Le commentaire sera communiqué au GEIQ.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["review_state"].required = True
        self.fields["review_state"].widget = forms.RadioSelect(choices=ReviewState.choices)
        self.fields["review_comment"].required = True
        self.fields["review_comment"].widget.attrs["placeholder"] = (
            "Merci de justifier votre choix en précisant le montant conventionné ainsi que le "
            "montant total de l’aide accordée, en euros."
        )
