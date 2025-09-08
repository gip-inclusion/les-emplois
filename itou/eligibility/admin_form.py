import logging

from django import forms

from itou.companies.models import CompanyMembership
from itou.eligibility.enums import AuthorKind
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind


logger = logging.getLogger(__name__)


class AbstractEligibilityDiagnosisAdminForm(forms.ModelForm):
    def clean_job_seeker(self):
        job_seeker = self.cleaned_data["job_seeker"]
        if job_seeker.kind != UserKind.JOB_SEEKER:
            raise forms.ValidationError("L'utilisateur doit être un candidat")
        return job_seeker

    def clean_author_kind(self):
        author_kind = self.cleaned_data["author_kind"]
        if author_kind not in [self.author_company_kind, AuthorKind.PRESCRIBER]:
            raise forms.ValidationError(
                f"Un {self._meta.model._meta.verbose_name} ne peut pas avoir ce type d'auteur."
            )
        return author_kind

    def clean(self):
        super().clean()

        author = self.cleaned_data.get("author")
        author_kind = self.cleaned_data.get("author_kind")
        author_prescriber_organization = self.cleaned_data.get("author_prescriber_organization")
        author_company = self.cleaned_data.get(self.author_company_fieldname)

        if author_prescriber_organization and author_company:
            self.add_error("__all__", "Vous ne pouvez pas saisir une entreprise et une organisation prescriptrice.")

        if author and author_kind:
            if author.kind == UserKind.PRESCRIBER:
                if not author_kind == AuthorKind.PRESCRIBER:
                    self.add_error("author_kind", "Le type ne correspond pas à l'auteur.")
                if not author_prescriber_organization:
                    self.add_error(
                        "author_prescriber_organization",
                        "Une organisation prescriptrice est obligatoire pour cet auteur.",
                    )
                elif not PrescriberMembership.include_inactive.filter(
                    organization=author_prescriber_organization, user=author
                ).exists():
                    # Allow inactive membership as we may want to fix old diagnoses
                    self.add_error("author_prescriber_organization", "L'auteur n'appartient pas à cette organisation.")
            elif author.kind == UserKind.EMPLOYER:
                if not author_kind == self.author_company_kind:
                    self.add_error("author_kind", "Le type ne correspond pas à l'auteur.")
                if not author_company:
                    if self.author_company_fieldname == "author_geiq":
                        company_name = "entreprise GEIQ"
                    else:
                        company_name = "SIAE"
                    self.add_error(
                        self.author_company_fieldname, f"Une {company_name} est obligatoire pour cet auteur."
                    )
                elif not CompanyMembership.include_inactive.filter(company=author_company, user=author).exists():
                    # Allow inactive membership as we may want to fix old diagnoses
                    self.add_error(self.author_company_fieldname, "L'auteur n'appartient pas à cette structure.")
            else:
                self.add_error("author", "Seul un prescripteur ou employeur peut être auteur d'un diagnostic.")


class GEIQEligibilityDiagnosisAdminForm(AbstractEligibilityDiagnosisAdminForm):
    author_company_fieldname = "author_geiq"
    author_company_kind = AuthorKind.GEIQ


class IAEEligibilityDiagnosisAdminForm(AbstractEligibilityDiagnosisAdminForm):
    author_company_fieldname = "author_siae"
    author_company_kind = AuthorKind.EMPLOYER
