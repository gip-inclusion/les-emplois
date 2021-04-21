from django import forms

from itou.approvals.models import Approval


class ManuallyAddApprovalForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Mandatory fields.
        self.fields["user"].required = True
        self.fields["start_at"].required = True
        self.fields["end_at"].required = True
        self.fields["created_by"].required = True

        # Optional fields.
        # The `number` field can be filled in manually by an admin when a Pôle emploi
        # approval already exists and needs to be re-issued by Itou.
        self.fields["number"].required = False

    class Meta:
        model = Approval
        fields = ["user", "start_at", "end_at", "number", "created_by"]
        widgets = {"user": forms.HiddenInput(), "created_by": forms.HiddenInput()}
        help_texts = {
            "number": "Laissez le champ vide pour générer automatiquement un numéro de PASS IAE.",
        }
