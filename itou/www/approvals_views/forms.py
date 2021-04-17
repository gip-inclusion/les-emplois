from django import forms
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, gettext_lazy

from itou.approvals.models import Prolongation, Suspension
from itou.users.models import User
from itou.utils.widgets import DatePickerField


class DeclareProlongationForm(forms.ModelForm):
    """
    Request a prolongation.

    Prolongation.clean() will handle the validation.
    """

    def __init__(self, *args, **kwargs):
        self.approval = kwargs.pop("approval")
        self.siae = kwargs.pop("siae")
        self.validated_by = None
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            # `start_at` should begin just after the approval. It cannot be set by the user.
            self.instance.start_at = Prolongation.get_start_at(self.approval)
            # `approval` must be set before model validation to avoid violating a not-null constraint.
            self.instance.approval = self.approval
            self.fields["reason"].initial = None  # Uncheck radio buttons.

        # `PARTICULAR_DIFFICULTIES` is allowed only for AI and ACI.
        if self.siae.kind not in [self.siae.KIND_AI, self.siae.KIND_ACI]:
            self.fields["reason"].choices = [
                item
                for item in self.fields["reason"].choices
                if item[0] != Prolongation.Reason.PARTICULAR_DIFFICULTIES
            ]

        self.fields["reason_explanation"].required = True  # Optional in admin but required for SIAEs.

        min_end_at_str = self.instance.start_at.strftime("%Y/%m/%d")
        max_end_at_str = Prolongation.get_max_end_at(self.instance.start_at).strftime("%Y/%m/%d")
        self.fields["end_at"].widget = DatePickerField({"minDate": min_end_at_str, "maxDate": max_end_at_str})
        self.fields["end_at"].input_formats = [DatePickerField.DATE_FORMAT]
        self.fields["end_at"].label = _(f'Du {self.instance.start_at.strftime("%d/%m/%Y")} au')

    email = forms.EmailField(
        required=True,
        label="E-mail du prescripteur habilité qui a autorisé cette prolongation",
        help_text=(
            "Attention : l'adresse e-mail doit correspondre à un compte utilisateur de type prescripteur habilité"
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        self.validated_by = User.objects.filter(email=email).first()
        if not self.validated_by or not self.validated_by.is_prescriber_with_authorized_org:
            error = "Cet utilisateur n'est pas un prescripteur habilité."
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
            "end_at": DatePickerField(),
            "reason": forms.RadioSelect(),
        }
        help_texts = {
            "end_at": mark_safe(
                (
                    "Date jusqu'à laquelle le PASS IAE doit être prolongé."
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

        if not self.instance.pk:
            self.instance.siae = self.siae
            self.instance.approval = self.approval
            self.fields["reason"].initial = None  # Uncheck radio buttons.

        today = timezone.now().date()
        min_start_at_str = Suspension.next_min_start_at(self.approval).strftime("%Y/%m/%d")
        max_end_at_str = Suspension.get_max_end_at(today).strftime("%Y/%m/%d")
        today_str = today.strftime("%Y/%m/%d")
        # A suspension is backdatable but cannot start in the future.
        self.fields["start_at"].widget = DatePickerField({"minDate": min_start_at_str, "maxDate": today_str})
        self.fields["end_at"].widget = DatePickerField({"minDate": min_start_at_str, "maxDate": max_end_at_str})

        for field in ["start_at", "end_at"]:
            self.fields[field].input_formats = [DatePickerField.DATE_FORMAT]

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
            "start_at": DatePickerField(),
            "end_at": DatePickerField(),
        }
        help_texts = {
            "start_at": mark_safe(
                (
                    "Au format JJ/MM/AAAA, par exemple 20/12/1978."
                    "<br>"
                    "La suspension ne peut pas commencer dans le futur."
                )
            ),
            "end_at": "Au format JJ/MM/AAAA, par exemple 20/12/1978.",
            "reason_explanation": "Obligatoire seulement en cas de force majeure.",
        }
