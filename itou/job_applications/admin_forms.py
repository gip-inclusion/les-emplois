import copy

from django import forms
from django.core.exceptions import ValidationError

from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import ACCEPTED_ONLY_FIELDS, JobApplication


class JobApplicationAdminForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = "__all__"
        labels = {
            "sender_company": "Entreprise émettrice (si type est Employeur)",
            "sender_prescriber_organization": "Organisation émettrice (si type est Prescripteur)",
        }

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if self.instance is None:
            self._initial_job_application_state = None
        else:
            self._initial_job_application_state = self.instance.state
        self._job_application_to_accept = data is not None and "transition_accept" in data

    def clean(self):
        super().clean()
        sender = self.cleaned_data["sender"]

        if "sender_kind" not in self.cleaned_data:
            raise ValidationError("Type émetteur manquant.")

        sender_kind = self.cleaned_data["sender_kind"]
        sender_company = self.cleaned_data.get("sender_company")
        sender_prescriber_organization = self.cleaned_data.get("sender_prescriber_organization")

        if sender_kind == SenderKind.JOB_SEEKER:
            if sender is None:
                raise ValidationError("Émetteur candidat manquant.")
            if not sender.is_job_seeker:
                raise ValidationError("Émetteur du mauvais type.")

        if sender_kind == SenderKind.EMPLOYER:
            if sender_company is None:
                raise ValidationError("SIAE émettrice manquante.")
            if sender is None:
                raise ValidationError("Émetteur SIAE manquant.")
            else:
                # Sender is optional, but if it exists, check its role.
                if not sender.is_professional:
                    raise ValidationError("Émetteur du mauvais type.")

        elif sender_company is not None:
            raise ValidationError("SIAE émettrice inattendue.")

        if sender_kind == SenderKind.PRESCRIBER:
            if sender:
                # Sender is optional, but if it exists, check its role.
                if not sender.is_professional:
                    raise ValidationError("Émetteur du mauvais type.")
                # Request organization only if prescriber is actively linked to an organization
                if sender_prescriber_organization is None and sender.prescribermembership_set.exists():
                    raise ValidationError("Organisation du prescripteur émettrice manquante.")
            else:
                raise ValidationError("Émetteur prescripteur manquant.")
        elif sender_prescriber_organization is not None:
            raise ValidationError("Organisation du prescripteur émettrice inattendue.")

        eligibility_diagnosis = self.cleaned_data.get("eligibility_diagnosis") or self.cleaned_data.get(
            "geiq_eligibility_diagnosis"
        )
        if eligibility_diagnosis:
            job_seeker = self.cleaned_data.get("job_seeker")
            if job_seeker.pk != eligibility_diagnosis.job_seeker_id:
                raise ValidationError("Le diagnostic d'éligibilité n'appartient pas au candidat de la candidature.")

        return

    def validate_constraints(self):
        """Override the default implementation to include the DB constraints on `state`.

        `state` is managed by xworkflows and the ACCEPTED_ONLY_FIELDS are admin readonly.
        Both end up excluded by the default logic, which would silently skip the
        `accepted_only_fields` check constraint. Force their inclusion here so the
        constraint is actually evaluated against the instance's current values.
        """
        exclude = self._get_validation_exclusions()
        exclude.discard("state")
        exclude.difference_update(ACCEPTED_ONLY_FIELDS)
        # Validate against a shallow copy so we never temporarily mutate the real
        # instance's state: this copy avoids a transient "accepted" state on the
        # instance being saved
        instance = copy.copy(self.instance)
        if self._job_application_to_accept:
            instance.state = JobApplicationState.ACCEPTED
        try:
            instance.validate_constraints(exclude=exclude)
        except ValidationError as e:
            self._update_errors(e)
