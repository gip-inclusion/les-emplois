from django import forms

from itou.approvals.models import Approval


class ApprovalFormMixin:

    ADDITIONAL_HELP_TEXT_NUMBER = " Laissez le champ vide pour générer automatiquement un numéro de PASS IAE."
    ERROR_NUMBER = (
        f"Les numéros préfixés par {Approval.ASP_ITOU_PREFIX} sont attribués automatiquement. "
        "Laissez le champ vide pour une génération automatique."
    )
    ERROR_NUMBER_CANNOT_BE_CHANGED = (
        "Vous ne pouvez modifier le numéro existant du PASS IAE %s "
        f"que vers un numéro ne commencant pas par {Approval.ASP_ITOU_PREFIX}."
    )

    def clean_number(self):
        number = self.cleaned_data["number"]
        is_new = self.instance.pk is None

        # A number starting with `ASP_ITOU_PREFIX` could create gaps`
        # in the automatic number sequence.
        if is_new and number and number.startswith(Approval.ASP_ITOU_PREFIX):
            raise forms.ValidationError(self.ERROR_NUMBER)

        # Allow to modify an existing PASS IAE to change its dates, but its number can only be changed if the new
        # number doesn't start with `ASP_ITOU_PREFIX`.
        if not is_new and number != self.instance.number and number.startswith(Approval.ASP_ITOU_PREFIX):
            raise forms.ValidationError(self.ERROR_NUMBER_CANNOT_BE_CHANGED % self.instance.number)

        return number


class ApprovalAdminForm(ApprovalFormMixin, forms.ModelForm):
    class Meta:
        model = Approval
        fields = ["start_at", "end_at", "user", "number", "created_by", "origin", "eligibility_diagnosis"]
        widgets = {"created_by": forms.HiddenInput(), "origin": forms.HiddenInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # TODO(alaurent) Update when all old approvals have a diagnosis
        if not self.instance.pk:
            self.fields["eligibility_diagnosis"].required = True

        # ex nihilo with arbitrary numbers because we have noticed holes in
        # the approvals transmitted by PE and we have complaints from users.
        if "number" in self.fields:
            self.fields["number"].required = False
            self.fields["number"].help_text += self.ADDITIONAL_HELP_TEXT_NUMBER

    def clean_eligibility_diagnosis(self):
        eligibility_diagnosis = self.cleaned_data["eligibility_diagnosis"]
        if eligibility_diagnosis and eligibility_diagnosis.job_seeker != self.cleaned_data["user"]:
            # Could we filter available eligibility diagnosis ?
            raise forms.ValidationError("Le diagnostique doit appartenir au même utilisateur que le PASS")
        return eligibility_diagnosis


class ManuallyAddApprovalFromJobApplicationForm(ApprovalFormMixin, forms.ModelForm):
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
        fields = ["user", "start_at", "end_at", "number", "created_by", "origin"]
        widgets = {"user": forms.HiddenInput(), "created_by": forms.HiddenInput(), "origin": forms.HiddenInput()}
