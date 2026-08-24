from django import forms
from django.contrib.admin import widgets
from django.core.exceptions import ValidationError

from itou.approvals.models import Approval
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.job_applications.enums import JobApplicationState, Origin
from itou.job_applications.models import JobApplication
from itou.utils.admin import FakeRelForRawIdWidget


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

        # Allow to modify an existing PASS IAE to change its dates, but its number can only be changed if the new
        # number doesn't start with `ASP_ITOU_PREFIX`.
        if not is_new and number != self.instance.number and number.startswith(Approval.ASP_ITOU_PREFIX):
            raise forms.ValidationError(self.ERROR_NUMBER_CANNOT_BE_CHANGED % self.instance.number)

        return number


class ApprovalAdminForm(forms.ModelForm):
    class Meta:
        model = Approval
        fields = ["start_at", "user", "eligibility_diagnosis"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk and (self.instance.suspension_set.exists() or self.instance.prolongation_set.exists()):
            obnoxious_warning = (
                '<ul class="messagelist"><li class="warning">En cas de modification, '
                "vérifier la cohérence avec les périodes de suspension et de prolongation.</li></ul>"
            )
            if "start_at" in self.fields:
                self.fields["start_at"].help_text = obnoxious_warning

    def clean_start_at(self):
        start_at = self.cleaned_data["start_at"]
        if (
            self.instance.prolongation_set.filter(start_at__lt=start_at).exists()
            or self.instance.suspension_set.filter(start_at__lt=start_at).exists()
        ):
            raise ValidationError("Cette date ne peut pas être après le début d’une prolongation ou d’une suspension.")
        return start_at

    def clean(self):
        super().clean()

        eligibility_diagnosis = self.cleaned_data.get("eligibility_diagnosis")
        if eligibility_diagnosis and eligibility_diagnosis.job_seeker != self.cleaned_data["user"]:
            # Could we filter available eligibility diagnosis ?
            self.add_error("eligibility_diagnosis", "Le diagnostic doit appartenir au même utilisateur que le PASS")
        elif not eligibility_diagnosis and self.instance.origin in [Origin.ADMIN, Origin.DEFAULT]:
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


class ProlongationDerogationForm(forms.Form):
    """Select the company to which a derogation link for an out-of-deadline prolongation is issued."""

    company = forms.ModelChoiceField(
        Company.objects.filter(kind__in=CompanyKind.siae_kinds()),
        required=True,
        label="SIAE autorisée à déclarer la prolongation",
        help_text="Saisissez l’ID de la SIAE, ou recherchez-la avec la loupe.",
        error_messages={
            "invalid_choice": (
                "Cette entreprise n’existe pas ou n’est pas une SIAE, elle ne peut pas déclarer de prolongation."
            )
        },
    )

    def __init__(self, *args, approval, admin_site, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].widget = widgets.ForeignKeyRawIdWidget(
            FakeRelForRawIdWidget(Company, limit_choices_to={"kind__in": CompanyKind.siae_kinds()}), admin_site
        )
        self.approval = approval

    def clean_company(self):
        """Mirrors checks performed by `declare_prolongation` to never hand out a link leading to a 404/403."""
        company = self.cleaned_data["company"]
        if not JobApplication.objects.filter(
            approval=self.approval, to_company=company, state=JobApplicationState.ACCEPTED
        ).exists():
            raise ValidationError("Cette entreprise n’a pas de candidature acceptée liée à ce PASS IAE.")
        return company
