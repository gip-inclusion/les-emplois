from django import forms

from itou.approvals.models import Approval
from itou.job_applications.enums import Origin


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
        # ex nihilo with arbitrary numbers because we have noticed holes in
        # the approvals transmitted by PE and we have complaints from users.
        if "number" in self.fields:
            self.fields["number"].required = False
            self.fields["number"].help_text += self.ADDITIONAL_HELP_TEXT_NUMBER

        if self.instance.pk and (self.instance.suspension_set.exists() or self.instance.prolongation_set.exists()):
            obnoxious_warning = (
                '<ul class="messagelist"><li class="warning">En cas de modification, '
                "vérifier la cohérence avec les périodes de suspension et de prolongation.</li></ul>"
            )
            if "start_at" in self.fields:
                self.fields["start_at"].help_text = obnoxious_warning
            if "end_at" in self.fields:
                self.fields["end_at"].help_text = obnoxious_warning

    def get_origin(self):
        if self.instance.pk:
            return self.instance.origin
        return self.cleaned_data["origin"]

    def set_origin(self):
        number = self.cleaned_data.get("number")
        # Only set to PE approval if there's a number and it's not from ITOU
        if number and not number.startswith(Approval.ASP_ITOU_PREFIX):
            self.cleaned_data["origin"] = Origin.PE_APPROVAL
        else:
            self.cleaned_data["origin"] = Origin.ADMIN

    def clean(self):
        super().clean()

        if "origin" in self.cleaned_data:
            self.set_origin()

        eligibility_diagnosis = self.cleaned_data.get("eligibility_diagnosis")
        if eligibility_diagnosis and eligibility_diagnosis.job_seeker != self.cleaned_data["user"]:
            # Could we filter available eligibility diagnosis ?
            self.add_error("eligibility_diagnosis", "Le diagnostic doit appartenir au même utilisateur que le PASS")
        elif not eligibility_diagnosis and self.get_origin() in [Origin.ADMIN, Origin.DEFAULT]:
            self.add_error("eligibility_diagnosis", "Ce champ est obligatoire")


class ManuallyAddApprovalFromJobApplicationForm(ApprovalFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Mandatory fields.
        self.fields["start_at"].required = True
        self.fields["end_at"].required = True

        # Optional fields.
        # The `number` field can be filled in manually by an admin when a Pôle emploi
        # approval already exists and needs to be re-issued by Itou.
        self.fields["number"].required = False
        self.fields["number"].help_text += self.ADDITIONAL_HELP_TEXT_NUMBER

    class Meta:
        model = Approval
        fields = ["start_at", "end_at", "number"]
