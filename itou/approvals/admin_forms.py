from django import forms

from itou.approvals.models import Approval


class ApprovalFormMixin:

    ADDITIONAL_HELP_TEXT_NUMBER = " Laissez le champ vide pour générer automatiquement un numéro de PASS IAE."
    ERROR_NUMBER = (
        f"Les numéros préfixés par {Approval.ASP_ITOU_PREFIX} sont attribués automatiquement. "
        "Laissez le champ vide pour une génération automatique."
    )
    ERROR_NUMBER_CANNOT_BE_CHANGED = "Vous ne pouvez pas modifier le numéro existant du PASS IAE %s."

    def clean_number(self):
        number = self.cleaned_data["number"]
        is_new = self.instance.pk is None
        if is_new and number and number.startswith(Approval.ASP_ITOU_PREFIX):
            # On ne laisse pas saisir un numéro qui commencerait par `ASP_ITOU_PREFIX`
            # car ça risquerait de créer des trous dans la séquence des numéros.
            raise forms.ValidationError(self.ERROR_NUMBER)
        elif number != self.instance.number:
            # On laisse la possibilité de modifier un PASS IAE existant afin
            # de pouvoir modifier ses dates, mais pas son numéro.
            raise forms.ValidationError(self.ERROR_NUMBER_CANNOT_BE_CHANGED % self.instance.number)
        return number


class ApprovalAdminForm(ApprovalFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # L'interface d'admin doit donner la possibilité de créer des PASS IAE
        # ex nihilo avec des numéros arbitraires car nous avons constaté des
        # trous dans les agréments transmis par PE et nous avons des
        # réclamations côté support.
        self.fields["number"].required = False
        self.fields["number"].help_text += self.ADDITIONAL_HELP_TEXT_NUMBER


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
        self.fields["number"].help_text += self.ADDITIONAL_HELP_TEXT_NUMBER

    class Meta:
        model = Approval
        fields = ["user", "start_at", "end_at", "number", "created_by"]
        widgets = {"user": forms.HiddenInput(), "created_by": forms.HiddenInput()}
