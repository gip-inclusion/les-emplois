from django import forms
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model

from itou.job_applications.models import JobRequest


class JobRequestForm(forms.ModelForm):
    """
    Submit a job request to an SIAE.
    """

    def __init__(self, user, siae, *args, **kwargs):
        self.prescriber_user = None
        self.siae = siae
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["jobs"].queryset = siae.jobs.filter(siaejobs__is_active=True)
        self.fields["motivation_message"].required = True

    prescriber_user_email = forms.EmailField(
        required=False, label=_("E-mail de votre accompagnateur (optionnel)")
    )

    class Meta:
        model = JobRequest
        fields = ["prescriber_user_email", "jobs", "motivation_message"]
        widgets = {"jobs": forms.CheckboxSelectMultiple()}
        labels = {"jobs": _("Métiers recherchés (optionnel)")}

    def clean_prescriber_user_email(self):
        """
        Retrieve a user instance from the `prescriber_user_email` field.
        """
        prescriber_user_email = self.cleaned_data["prescriber_user_email"]
        if prescriber_user_email:
            try:
                self.prescriber_user = get_user_model().objects.get(
                    email=prescriber_user_email, is_prescriber=True
                )
            except get_user_model().DoesNotExist:
                error = _(
                    "Cet accompagnateur ne figure pas dans notre base de données."
                )
                raise forms.ValidationError(error)
        return prescriber_user_email

    def save(self, commit=True):
        job_request = super().save(commit=False)
        job_request.job_seeker = self.user
        job_request.siae = self.siae
        if self.prescriber_user:
            job_request.prescriber_user = self.prescriber_user
            # Assume we have only one organization per prescriber staff at the moment
            job_request.prescriber = job_request.prescriber_user.prescriber_set.first()
        if commit:
            job_request.save()
            # Handle many to many.
            for job in self.cleaned_data["jobs"]:
                job_request.jobs.add(job)
        return job_request
