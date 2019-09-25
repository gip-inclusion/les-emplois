from django import forms
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model

from itou.job_applications.models import JobApplication, JobApplicationWorkflow


class JobApplicationForm(forms.ModelForm):
    """
    Submit a job application to an SIAE.
    """

    def __init__(self, user, siae, *args, **kwargs):
        self.prescriber = None
        self.siae = siae
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["jobs"].queryset = siae.jobs.filter(
            siaejobdescription__is_active=True
        )
        self.fields["message"].required = True

    prescriber_email = forms.EmailField(
        required=False, label=_("E-mail de votre accompagnateur (optionnel)")
    )

    class Meta:
        model = JobApplication
        fields = ["prescriber_email", "jobs", "message"]
        widgets = {"jobs": forms.CheckboxSelectMultiple()}
        labels = {"jobs": _("Métiers recherchés (optionnel)")}

    def clean_prescriber_email(self):
        """
        Retrieve a user instance from the `prescriber_email` field.
        """
        prescriber_email = self.cleaned_data["prescriber_email"]
        if prescriber_email:
            try:
                self.prescriber = get_user_model().objects.get(
                    email=prescriber_email, is_prescriber=True
                )
            except get_user_model().DoesNotExist:
                error = _(
                    "Cet accompagnateur ne figure pas dans notre base de données."
                )
                raise forms.ValidationError(error)
        return prescriber_email

    def save(self, commit=True):
        job_application = super().save(commit=False)
        job_application.job_seeker = self.user
        job_application.siae = self.siae
        if self.prescriber:
            job_application.prescriber = self.prescriber
            # Assume we have 0 or 1 organization per prescriber at the moment.
            job_application.prescriber_organization = (
                job_application.prescriber.prescriberorganization_set.first()
            )
        if commit:
            job_application.save()
            # Handle many to many.
            for job in self.cleaned_data["jobs"]:
                job_application.jobs.add(job)
        return job_application


class JobApplicationProcessForm(forms.Form):
    """
    Allow an SIAE to choose between rejecting or processing a job application.
    """

    TRANSITION_CHOICES = dict(JobApplicationWorkflow.TRANSITION_CHOICES)

    ACTION_PROCESS = JobApplicationWorkflow.TRANSITION_PROCESS
    ACTION_REJECT = JobApplicationWorkflow.TRANSITION_REJECT

    ACTION_CHOICES = [
        (ACTION_REJECT, TRANSITION_CHOICES[ACTION_REJECT]),
        (ACTION_PROCESS, TRANSITION_CHOICES[ACTION_PROCESS]),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES, widget=forms.HiddenInput())
    answer = forms.CharField(
        label=_("Réponse"), widget=forms.Textarea(), required=False, strip=True
    )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        answer = cleaned_data.get("answer")
        if action == self.ACTION_REJECT and not answer:
            error = _("Une réponse est obligatoire pour décliner une candidature.")
            raise forms.ValidationError(error)


class JobApplicationAnswerForm(forms.Form):
    """
    Let an SIAE give a definitive answer to a job application.
    """

    TRANSITION_CHOICES = dict(JobApplicationWorkflow.TRANSITION_CHOICES)

    ACTION_ACCEPT = JobApplicationWorkflow.TRANSITION_ACCEPT
    ACTION_REJECT = JobApplicationWorkflow.TRANSITION_REJECT

    ACTION_CHOICES = [
        (ACTION_REJECT, TRANSITION_CHOICES[ACTION_REJECT]),
        (ACTION_ACCEPT, TRANSITION_CHOICES[ACTION_ACCEPT]),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES, widget=forms.HiddenInput())
    answer = forms.CharField(
        label=_("Réponse"),
        widget=forms.Textarea(),
        help_text="Votre réponse est obligatoire.",
        strip=True,
    )
