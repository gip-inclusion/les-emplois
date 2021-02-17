from django import forms

from itou.approvals.models import Approval, Prolongation


class ManuallyAddApprovalForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].required = True

    class Meta:
        model = Approval
        fields = ["user", "start_at", "end_at", "number", "created_by"]
        widgets = {"user": forms.HiddenInput(), "created_by": forms.HiddenInput()}


class ProlongationForm(forms.ModelForm):
    class Meta:
        model = Prolongation
        fields = ["start_at", "end_at"]
