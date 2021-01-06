from django import forms
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy

from itou.approvals.models import Suspension
from itou.utils.widgets import DatePickerField


class SuspensionForm(forms.ModelForm):
    """
    Create or edit a suspension.
    """

    def __init__(self, approval, *args, **kwargs):
        self.approval = approval
        super().__init__(*args, **kwargs)

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
            "approval",
            "start_at",
            "end_at",
            "siae",
            "reason",
            "reason_explanation",
        ]
        widgets = {
            "siae": forms.HiddenInput(),
            "approval": forms.HiddenInput(),
            "reason": forms.RadioSelect(),
        }
        help_texts = {
            "start_at": mark_safe(
                gettext_lazy(
                    "Au format JJ/MM/AAAA, par exemple 20/12/1978."
                    "<br>"
                    "La suspension ne peut pas commencer dans le futur."
                )
            ),
            "end_at": gettext_lazy("Au format JJ/MM/AAAA, par exemple 20/12/1978."),
            "reason_explanation": gettext_lazy("Obligatoire seulement en cas de force majeure."),
        }
