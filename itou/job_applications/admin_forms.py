from django import forms
from django.core.exceptions import ValidationError

from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication


class JobApplicationAdminForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = "__all__"

    def clean(self):
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
                # Request organization only if prescriber is linked to organization
                if sender.is_prescriber_with_org and sender_prescriber_organization is None:
                    raise ValidationError("Organisation du prescripteur émettrice manquante.")
            else:
                raise ValidationError("Emetteur prescripteur manquant.")
        elif sender_prescriber_organization is not None:
            raise ValidationError("Organisation du prescripteur émettrice inattendue.")

        return
