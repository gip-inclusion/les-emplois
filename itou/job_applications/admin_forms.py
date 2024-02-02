from django import forms
from django.core.exceptions import ValidationError

from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow


class JobApplicationAdminForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = "__all__"
        labels = {
            "sender_company": "Entreprise émettrice (si type est Employeur)",
            "sender_prescriber_organization": "Organisation émettrice (si type est Prescripteur)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            self._initial_job_application_state = None
        else:
            self._initial_job_application_state = self.instance.state
        self._job_application_to_accept = False

    def clean(self):
        target_state = self.cleaned_data.get("state")
        if (
            target_state == JobApplicationWorkflow.STATE_ACCEPTED
            and target_state != self._initial_job_application_state
        ):
            self._job_application_to_accept = True
            self.cleaned_data["state"] = self._initial_job_application_state or JobApplicationWorkflow.STATE_NEW

        if self._job_application_to_accept and not self.cleaned_data.get("hiring_start_at"):
            self.add_error("hiring_start_at", "Ce champ est obligatoire pour les candidatures acceptées.")

        if (
            self._job_application_to_accept
            and (to_company := self.cleaned_data.get("to_company"))
            and to_company.is_subject_to_eligibility_rules
            and self.cleaned_data.get("hiring_without_approval") is not True
            and (job_seeker := self.cleaned_data.get("job_seeker"))
            and not job_seeker.has_valid_common_approval
            and not EligibilityDiagnosis.objects.last_considered_valid(job_seeker, for_siae=to_company)
        ):
            self.add_error(
                None,
                (
                    "Un diagnostic d'éligibilité valide pour ce candidat "
                    "et cette SIAE est obligatoire pour pouvoir créer un PASS IAE."
                ),
            )

        sender = self.cleaned_data["sender"]
        sender_kind = self.cleaned_data["sender_kind"]
        sender_company = self.cleaned_data.get("sender_company")
        sender_prescriber_organization = self.cleaned_data.get("sender_prescriber_organization")

        if sender_kind == SenderKind.JOB_SEEKER:
            if sender is None:
                raise ValidationError("Emetteur candidat manquant.")
            if not sender.is_job_seeker:
                raise ValidationError("Emetteur du mauvais type.")

        if sender_kind == SenderKind.EMPLOYER:
            if sender_company is None:
                raise ValidationError("SIAE émettrice manquante.")
            if sender is None:
                raise ValidationError("Emetteur SIAE manquant.")
            else:
                # Sender is optional, but if it exists, check its role.
                if not sender.is_employer:
                    raise ValidationError("Emetteur du mauvais type.")

        elif sender_company is not None:
            raise ValidationError("SIAE émettrice inattendue.")

        if sender_kind == SenderKind.PRESCRIBER:
            if sender:
                # Sender is optional, but if it exists, check its role.
                if not sender.is_prescriber:
                    raise ValidationError("Emetteur du mauvais type.")
                # Request organization only if prescriber is actively linked to an organization
                if (
                    sender_prescriber_organization is None
                    and sender.prescribermembership_set.filter(is_active=True).exists()
                ):
                    raise ValidationError("Organisation du prescripteur émettrice manquante.")
            else:
                raise ValidationError("Emetteur prescripteur manquant.")
        elif sender_prescriber_organization is not None:
            raise ValidationError("Organisation du prescripteur émettrice inattendue.")

        return
