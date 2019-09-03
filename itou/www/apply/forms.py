from django import forms
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model

from itou.job_applications.models import JobApplication, JobApplicationWorkflow


class JobApplicationForm(forms.ModelForm):
    """
    Submit a job application to an SIAE.
    """

    def __init__(self, user, siae, *args, **kwargs):
        self.prescriber_user = None
        self.siae = siae
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["jobs"].queryset = siae.jobs.filter(siaejobs__is_active=True)
        self.fields["message"].required = True

    prescriber_user_email = forms.EmailField(
        required=False, label=_("E-mail de votre accompagnateur (optionnel)")
    )

    class Meta:
        model = JobApplication
        fields = ["prescriber_user_email", "jobs", "message"]
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
                    email=prescriber_user_email, is_prescriber_staff=True
                )
            except get_user_model().DoesNotExist:
                error = _(
                    "Cet accompagnateur ne figure pas dans notre base de données."
                )
                raise forms.ValidationError(error)
        return prescriber_user_email

    def save(self, commit=True):
        job_application = super().save(commit=False)
        job_application.job_seeker = self.user
        job_application.siae = self.siae
        if self.prescriber_user:
            job_application.prescriber_user = self.prescriber_user
            # Assume we have only one organization per prescriber staff at the moment
            job_application.prescriber = (
                job_application.prescriber_user.prescriber_set.first()
            )
        if commit:
            job_application.save()
            # Handle many to many.
            for job in self.cleaned_data["jobs"]:
                job_application.jobs.add(job)
        return job_application


class JobApplicationAnswerForm(forms.Form):
    """
    Let an SIAE answer to a job application.
    """

    ANSWER_KIND_ACCEPT = JobApplicationWorkflow.TRANSITION_ACCEPT
    ANSWER_KIND_REJECT = JobApplicationWorkflow.TRANSITION_REJECT
    ANSWER_KIND_CHOICES = [
        (ANSWER_KIND_ACCEPT, ANSWER_KIND_ACCEPT),
        (ANSWER_KIND_REJECT, ANSWER_KIND_REJECT),
    ]

    answer_kind = forms.ChoiceField(
        choices=ANSWER_KIND_CHOICES, widget=forms.HiddenInput()
    )
    answer = forms.CharField(
        label=_("Réponse"),
        widget=forms.Textarea(),
        help_text="Votre réponse est obligatoire.",
    )
