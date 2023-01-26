from dateutil.relativedelta import relativedelta
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.forms import widgets
from django.utils import timezone
from django.utils.safestring import mark_safe

from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import (
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
)
from itou.utils.types import InclusiveDateRange
from itou.utils.widgets import DuetDatePickerWidget


class SetChosenPercentForm(forms.ModelForm):
    opt_out = forms.BooleanField(
        label="Je choisis de ne pas débuter le contrôle",
        required=False,
        widget=widgets.CheckboxInput(
            attrs={
                "aria-expanded": "true",
                "aria-controls": "ratio-select",
                "data-target": "#ratio-select",
                "data-toggle": "collapse",
            }
        ),
    )

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Use default when not specified. Can be omitted when opt_out is True.
        self.fields["chosen_percent"].required = False


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
        if instance.evaluated_siae.evaluation_is_final:
            self.fields["labor_inspector_explanation"].disabled = True
        if instance.labor_inspector_explanation:
            self.initial["labor_inspector_explanation"] = instance.labor_inspector_explanation


class InstitutionEvaluatedSiaeNotifyStep1Form(forms.ModelForm):
    notification_reason = forms.ChoiceField(
        choices=evaluation_enums.EvaluatedSiaeNotificationReason.choices,
        widget=forms.RadioSelect(),
        required=True,
        label="Raison principale",
    )

    class Meta:
        model = EvaluatedSiae
        fields = ["notification_reason", "notification_text"]
        widgets = {
            "notification_text": forms.Textarea(
                attrs={
                    "placeholder": (
                        "Merci de renseigner ici les raisons qui ont mené à un contrôle a posteriori des "
                        "auto-prescriptions non conforme."
                    ),
                },
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notification_text"].required = True


TRAINING = "TRAINING"
TEMPORARY_SUSPENSION = "TEMPORARY_SUSPENSION"
PERMANENT_SUSPENSION = "PERMANENT_SUSPENSION"
SUBSIDY_CUT_PERCENT = "SUBSIDY_CUT_PERCENT"
SUBSIDY_CUT_FULL = "SUBSIDY_CUT_FULL"
DEACTIVATION = "DEACTIVATION"
NO_SANCTIONS = "NO_SANCTIONS"
SANCTION_CHOICES = {
    TRAINING: "Participation à une session de présentation de l’auto-prescription",
    TEMPORARY_SUSPENSION: "Retrait temporaire de la capacité d’auto-prescription",
    PERMANENT_SUSPENSION: "Retrait définitif de la capacité d’auto-prescription",
    SUBSIDY_CUT_PERCENT: "Suppression d’une partie de l’aide au poste",
    SUBSIDY_CUT_FULL: "Suppression de toute l’aide au poste",
    DEACTIVATION: "Déconventionnement de la structure",
    NO_SANCTIONS: "Ne pas sanctionner",
}


class InstitutionEvaluatedSiaeNotifyStep2Form(forms.Form):
    sanctions = forms.MultipleChoiceField(
        choices=SANCTION_CHOICES.items(),
        label="Cochez la ou les sanctions",
        widget=forms.CheckboxSelectMultiple(),
    )

    def incompatible_error(self, field1, field2):
        return ValidationError(
            "“%(field1)s” est incompatible avec “%(field2)s”, choisissez l’une ou l’autre de ces sanctions.",
            code="invalid",
            params={"field1": SANCTION_CHOICES[field1], "field2": SANCTION_CHOICES[field2]},
        )

    def clean(self):
        cleaned_data = super().clean()
        if not self.errors:
            sanctions = set(cleaned_data["sanctions"])
            errors = []
            if sanctions.issuperset({TEMPORARY_SUSPENSION, PERMANENT_SUSPENSION}):
                errors.append(self.incompatible_error(TEMPORARY_SUSPENSION, PERMANENT_SUSPENSION))
            if sanctions.issuperset({SUBSIDY_CUT_FULL, SUBSIDY_CUT_PERCENT}):
                errors.append(self.incompatible_error(SUBSIDY_CUT_PERCENT, SUBSIDY_CUT_FULL))
            if len(sanctions) > 1 and NO_SANCTIONS in sanctions:
                errors.append(
                    ValidationError(
                        "“%(no_sanction)s” est incompatible avec les autres sanctions.",
                        code="invalid",
                        params={"no_sanction": SANCTION_CHOICES[NO_SANCTIONS]},
                    )
                )
            if errors:
                raise ValidationError(errors)
        return cleaned_data


class InstitutionEvaluatedSiaeNotifyStep3Form(forms.Form):
    def __init__(self, *args, sanctions, **kwargs):
        super().__init__(*args, **kwargs)
        if TRAINING in sanctions:
            self.fields["training_session"] = forms.CharField(
                label="Préciser ici les modalités à la SIAE",
                help_text=("Détails concernant la session de présentation (quand, comment, avec qui, etc.)"),
                widget=forms.Textarea(
                    attrs={"placeholder": "Merci de renseigner ici les détails concernant la session de présentation"}
                ),
            )
        sanction_start_date = timezone.localdate() + relativedelta(months=1)
        if TEMPORARY_SUSPENSION in sanctions:
            self.fields["temporary_suspension_from"] = forms.DateField(
                label="À partir du",
                validators=[MinValueValidator(sanction_start_date)],
                widget=DuetDatePickerWidget(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[TEMPORARY_SUSPENSION]} à partir du",
                        "min": sanction_start_date,
                        "placeholder": False,
                    }
                ),
            )
            self.fields["temporary_suspension_to"] = forms.DateField(
                label="Jusqu’au",
                validators=[MinValueValidator(sanction_start_date)],
                widget=DuetDatePickerWidget(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[TEMPORARY_SUSPENSION]} jusqu’au",
                        "min": sanction_start_date,
                        "placeholder": False,
                    }
                ),
            )
        if PERMANENT_SUSPENSION in sanctions:
            self.fields["permanent_suspension"] = forms.DateField(
                label="À partir du",
                validators=[MinValueValidator(sanction_start_date)],
                widget=DuetDatePickerWidget(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[PERMANENT_SUSPENSION]} à partir du",
                        "min": sanction_start_date,
                        "placeholder": False,
                    }
                ),
            )
        if SUBSIDY_CUT_PERCENT in sanctions:
            self.fields["subsidy_cut_percent"] = forms.IntegerField(
                label="Pourcentage d’aide retiré à la SIAE",
                min_value=1,
                max_value=100,
                widget=forms.NumberInput(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[SUBSIDY_CUT_PERCENT]} à partir du",
                        "placeholder": "Pourcentage d’aide retiré à la SIAE",
                        "step": "1",
                    },
                ),
            )
            self.fields["subsidy_cut_from"] = forms.DateField(
                label="À partir du",
                widget=DuetDatePickerWidget(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[SUBSIDY_CUT_PERCENT]} à partir du",
                        "placeholder": False,
                    }
                ),
            )
            self.fields["subsidy_cut_to"] = forms.DateField(
                label="Jusqu’au",
                widget=DuetDatePickerWidget(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[SUBSIDY_CUT_PERCENT]} jusqu’au",
                        "placeholder": False,
                    }
                ),
            )
        if SUBSIDY_CUT_FULL in sanctions:
            self.fields["subsidy_cut_from"] = forms.DateField(
                label="À partir du",
                widget=DuetDatePickerWidget(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[SUBSIDY_CUT_FULL]} à partir du",
                        "placeholder": False,
                    }
                ),
            )
            self.fields["subsidy_cut_to"] = forms.DateField(
                label="Jusqu’au",
                widget=DuetDatePickerWidget(
                    attrs={
                        "aria-label": f"{SANCTION_CHOICES[SUBSIDY_CUT_FULL]} jusqu’au",
                        "placeholder": False,
                    }
                ),
            )
        if DEACTIVATION in sanctions:
            self.fields["deactivation_reason"] = forms.CharField(
                label="Préciser ici les modalités à la SIAE",
                help_text=(
                    "Les étapes, recours, etc. seront communiqués de façon plus officielle par lettre recommandée "
                    "avec accusé de réception."
                ),
                widget=forms.Textarea(
                    attrs={"placeholder": "Merci de renseigner ici les détails concernant le déconventionnement"}
                ),
            )
        if NO_SANCTIONS in sanctions:
            self.fields["no_sanction_reason"] = forms.CharField(
                label="Préciser ici les modalités à la SIAE",
                help_text=mark_safe(
                    "<i>Exemple de message :<br></i>"
                    "Le contrôle de vos auto-prescriptions est négatif, une sanction devrait s’appliquer à "
                    "l’encontre de votre structure (préciser la sanction) cependant en raison (préciser : difficultés "
                    "financières, d’organisation, etc.), nous n’allons exceptionnellement pas appliquer la sanction "
                    "mais nous attirons votre attention sur le fait que nous restons vigilants et que nous serons "
                    "peut-être moins compréhensifs lors du prochain contrôle."
                ),
                widget=forms.Textarea(
                    attrs={"placeholder": "Merci de renseigner ici les raisons vous ayant amené à ne pas sanctionner."}
                ),
            )

    def clean(self):
        cleaned_data = super().clean()
        if not self.errors:
            if cleaned_data.get("subsidy_cut_from") and "subsidy_cut_percent" not in cleaned_data:
                cleaned_data["subsidy_cut_percent"] = 100
            if cleaned_data.get("subsidy_cut_from"):
                datefrom = cleaned_data["subsidy_cut_from"]
                dateto = cleaned_data["subsidy_cut_to"]
                if datefrom > dateto:
                    raise ValidationError(
                        "La date de fin de retrait de l’aide au poste ne peut pas être avant la date de début de "
                        "retrait de l’aide au poste."
                    )
                cleaned_data["subsidy_cut_dates"] = InclusiveDateRange(datefrom, dateto)
            if cleaned_data.get("temporary_suspension_from"):
                datefrom = cleaned_data["temporary_suspension_from"]
                dateto = cleaned_data["temporary_suspension_to"]
                if datefrom > dateto:
                    raise ValidationError(
                        "La date de fin de suspension ne peut pas être avant la date de début de suspension."
                    )
                cleaned_data["suspension_dates"] = InclusiveDateRange(datefrom, dateto)
            if cleaned_data.get("permanent_suspension"):
                cleaned_data["suspension_dates"] = InclusiveDateRange(cleaned_data["permanent_suspension"])
        return cleaned_data
