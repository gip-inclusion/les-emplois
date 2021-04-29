from django import forms

from itou.approvals.models import Approval


class ApprovalFormMixin:

    ERROR_NUMBER = (
        f"Les numéros préfixés par {Approval.ASP_ITOU_PREFIX} sont attribués automatiquement. "
        "Laissez le champ vide pour une génération automatique."
    )

    def clean_number(self):
        number = self.cleaned_data["number"]
        if number and number.startswith(Approval.ASP_ITOU_PREFIX):
            raise forms.ValidationError(self.ERROR_NUMBER)
        return number


class ApprovalAdminForm(ApprovalFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # L'interface d'admin doit donner la possibilité de créer des PASS IAE
        # ex nihilo avec des numéros arbitraires car nous avons constaté des
        # trous dans les agréments transmis par PE et nous avons des
        # réclamations côté support.
        self.fields["number"].required = False
        self.fields["number"].help_text += " Laissez le champ vide pour générer automatiquement un numéro de PASS IAE."


class ManuallyAddApprovalForm(ApprovalFormMixin, forms.ModelForm):
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
        self.fields["number"].help_text += " Laissez le champ vide pour générer automatiquement un numéro de PASS IAE."

    class Meta:
        model = Approval
        fields = ["user", "start_at", "end_at", "number", "created_by"]
        widgets = {"user": forms.HiddenInput(), "created_by": forms.HiddenInput()}
