from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.safestring import mark_safe

from itou.approvals.models import Prolongation, Suspension
from itou.users.models import User
from itou.utils.widgets import DuetDatePickerWidget


class DeclareProlongationForm(forms.ModelForm):
    """
    Request a prolongation.

    Prolongation.clean() will handle the validation.
    """

    def __init__(self, *args, **kwargs):
        self.approval = kwargs.pop("approval")
        self.siae = kwargs.pop("siae")
        self.validated_by = None
        self.reasons_not_need_prescriber_opinion = Prolongation.REASONS_NOT_NEED_PRESCRIBER_OPINION
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.instance.declared_by_siae = self.siae
            # `start_at` should begin just after the approval. It cannot be set by the user.
            self.instance.start_at = Prolongation.get_start_at(self.approval)
            # `approval` must be set before model validation to avoid violating a not-null constraint.
            self.instance.approval = self.approval
            self.fields["reason"].initial = None  # Uncheck radio buttons.

        self.reasons_max_duration_labels = {
            k: {"l": v["label"], "d": str(Prolongation.get_max_end_at(self.instance.start_at, k))}
            for (k, v) in Prolongation.MAX_CUMULATIVE_DURATION.items()
            if k != Prolongation.Reason.HEALTH_CONTEXT.value
        }

        # Since December 1, 2021, health context reason can no longer be used
        self.fields["reason"].choices = [
            item for item in self.fields["reason"].choices if item[0] != Prolongation.Reason.HEALTH_CONTEXT
        ]

        # `PARTICULAR_DIFFICULTIES` is allowed only for AI, ACI and ACIPHC.
        if self.siae.kind not in [self.siae.KIND_AI, self.siae.KIND_ACI, self.siae.KIND_ACIPHC]:
            self.fields["reason"].choices = [
                item
                for item in self.fields["reason"].choices
                if item[0] != Prolongation.Reason.PARTICULAR_DIFFICULTIES
            ]

        self.fields["reason_explanation"].required = True  # Optional in admin but required for SIAEs.

        self.fields["end_at"].widget = DuetDatePickerWidget(
            {"min": self.instance.start_at, "max": Prolongation.get_max_end_at(self.instance.start_at)}
        )
        self.fields["end_at"].label = f'Du {self.instance.start_at.strftime("%d/%m/%Y")} au'

    email = forms.EmailField(
        required=False,
        label="E-mail du prescripteur habilité qui a autorisé cette prolongation",
        help_text=(
            "Attention : l'adresse e-mail doit correspondre à un compte utilisateur de type prescripteur habilité"
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if self.cleaned_data.get("reason") in self.reasons_not_need_prescriber_opinion:
            email = None
        else:
            self.validated_by = User.objects.filter(email=email).first()
            if not self.validated_by or not self.validated_by.is_prescriber_with_authorized_org:
                error = (
                    "Ce prescripteur n'a pas de compte sur les emplois de l'inclusion. "
                    "Merci de renseigner l'e-mail d'un conseiller inscrit sur le service."
                )
                raise forms.ValidationError(error)
        return email

    class Meta:
        model = Prolongation
        fields = [
            # Order is important for the template.
            "reason",
            "end_at",
            "reason_explanation",
            "email",
        ]
        widgets = {
            "end_at": DuetDatePickerWidget(),
            "reason": forms.RadioSelect(),
        }
        help_texts = {
            "end_at": mark_safe(
                (
                    'Date jusqu\'à laquelle le PASS IAE doit être prolongé<strong id="js-duration-label"></strong>.'
                    "<br>"
                    "Au format JJ/MM/AAAA, par exemple 20/12/1978."
                )
            ),
        }


class SuspensionForm(forms.ModelForm):
    """
    Create or edit a suspension.

    Suspension.clean() will handle the validation.
    """

    def __init__(self, *args, **kwargs):
        self.approval = kwargs.pop("approval")
        self.siae = kwargs.pop("siae")
        super().__init__(*args, **kwargs)
        # Show new reasons but keep old ones for history.
        self.fields["reason"].choices = Suspension.Reason.displayed_choices

        if not self.instance.pk:
            self.instance.siae = self.siae
            self.instance.approval = self.approval
            self.fields["reason"].initial = None  # Uncheck radio buttons.

        today = timezone.now().date()
        min_start_at = Suspension.next_min_start_at(self.approval)
        # A suspension is backdatable but cannot start in the future.
        self.fields["start_at"].widget = DuetDatePickerWidget({"min": min_start_at, "max": today})
        self.fields["end_at"].widget = DuetDatePickerWidget(
            {"min": min_start_at, "max": Suspension.get_max_end_at(today)}
        )

    class Meta:
        model = Suspension
        fields = [
            # Order is important for the template.
            "start_at",
            "end_at",
            "reason",
            "reason_explanation",
        ]
        widgets = {
            "reason": forms.RadioSelect(),
            "start_at": DuetDatePickerWidget(),
            "end_at": DuetDatePickerWidget(),
        }
        help_texts = {
            "start_at": mark_safe(
                (
                    "Au format JJ/MM/AAAA, par exemple 20/12/1978."
                    "<br>"
                    "La suspension ne peut pas commencer dans le futur."
                )
            ),
            "end_at": mark_safe(
                (
                    "Au format JJ/MM/AAAA, par exemple 20/12/1978."
                    "<br>"
                    "Renseignez une date de fin à 12 mois si le contrat de travail est terminé ou rompu."
                )
            ),
            "reason_explanation": "Obligatoire seulement en cas de force majeure.",
        }


class PoleEmploiApprovalSearchForm(forms.Form):
    """
    Search for a PoleEmploiApproval by number
    """

    number = forms.CharField(
        label="Numéro",
        required=True,
        min_length=12,
        max_length=15,
        strip=True,
        help_text=("Le numéro d'agrément est composé de 12 chiffres (ex. 123456789012)."),
    )

    def clean_number(self):
        number = self.cleaned_data.get("number", "").replace(" ", "")
        if len(number) != 12:
            raise ValidationError(
                "Merci d'indiquer les 12 premiers caractères du numéro d'agrément. "
                "Exemple : 123456789012 si le numéro d'origine est 123456789012P01."
            )

        return number
