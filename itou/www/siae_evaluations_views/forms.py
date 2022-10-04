from django import forms
from django.conf import settings
from django.utils import timezone

from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria, EvaluatedJobApplication, EvaluationCampaign


class SetChosenPercentForm(forms.ModelForm):
    class Meta:
        model = EvaluationCampaign
        fields = ["chosen_percent"]
        widgets = {
            "chosen_percent": forms.TextInput(
                attrs={
                    "type": "range",
                    "class": "form-range slider",
                    "step": "1",
                    "min": evaluation_enums.EvaluationChosenPercent.MIN,
                    "max": evaluation_enums.EvaluationChosenPercent.MAX,
                    "id": "chosenPercentRange",
                }
            )
        }


class SubmitEvaluatedAdministrativeCriteriaProofForm(forms.ModelForm):
    class Meta:
        model = EvaluatedAdministrativeCriteria
        fields = ["proof_url"]

    def save(self):
        instance = super().save(commit=False)
        instance.uploaded_at = timezone.now()
        instance.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        instance.submitted_at = None
        instance.save(update_fields=["proof_url", "uploaded_at", "review_state", "submitted_at"])
        return instance

    def clean_proof_url(self):
        # re-use of itou.common_apps.resume.ResumeFormMixin.clean_resume_link
        # could be refatored later if we switch from URLField to FileField
        proof_url = self.cleaned_data.get("proof_url")
        # ensure the doc has been uploaded via our S3 platform and is not a link to a 3rd party website
        if proof_url and settings.S3_STORAGE_ENDPOINT_DOMAIN not in proof_url:
            self.add_error(
                "proof_url",
                forms.ValidationError("Le document sélectionné ne provient pas d'une source de confiance."),
            )
        return proof_url


class LaborExplanationForm(forms.ModelForm):
    class Meta:
        model = EvaluatedJobApplication
        fields = ["labor_inspector_explanation"]
        widgets = {
            "labor_inspector_explanation": forms.Textarea(
                attrs={"placeholder": "Vous pouvez indiquer ici une demande de justificatif complémentaire"}
            )
        }
        labels = {"labor_inspector_explanation": "Raison d'une auto-prescription refusée"}

    def __init__(self, instance, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if instance.evaluated_siae.evaluation_campaign.ended_at:
            self.fields["labor_inspector_explanation"].disabled = True
        if instance.labor_inspector_explanation:
            self.initial["labor_inspector_explanation"] = instance.labor_inspector_explanation
