from django import forms
from django.core.exceptions import ValidationError

from itou.job_applications.models import JobApplication


class JobApplicationAdminForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = "__all__"

    def clean(self):
        sender = self.cleaned_data["sender"]
        sender_kind = self.cleaned_data["sender_kind"]
        sender_siae = self.cleaned_data["sender_siae"]
        sender_prescriber_organization = self.cleaned_data["sender_prescriber_organization"]

        if sender_kind == JobApplication.SENDER_KIND_JOB_SEEKER:
            if sender is None:
                raise ValidationError("Emetteur candidat manquant.")
            if not sender.is_job_seeker:
                raise ValidationError("Emetteur du mauvais type.")

        if sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF:
            if sender_siae is None:
                raise ValidationError("SIAE émettrice manquante.")
            if sender is not None:
                # Sender is optional, but if it exists, check its role.
                if not sender.is_siae_staff:
                    raise ValidationError("Emetteur du mauvais type.")
        elif sender_siae is not None:
            raise ValidationError("SIAE émettrice inattendue.")

        if sender_kind == JobApplication.SENDER_KIND_PRESCRIBER:
            if sender_prescriber_organization is None:
                raise ValidationError("Organisation du prescripteur émettrice manquante.")
            if sender is not None:
                # Sender is optional, but if it exists, check its role.
                if not sender.is_prescriber:
                    raise ValidationError("Emetteur du mauvais type.")
        elif sender_prescriber_organization is not None:
            raise ValidationError("Organisation du prescripteur émettrice inattendue.")

        return
