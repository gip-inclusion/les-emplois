from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from itou.job_applications.models import JobApplication


class CheckJobSeekerForm(forms.Form):

    email = forms.EmailField(label=_("E-mail du candidat"))

    def get_job_seeker_from_email(self):
        email = self.cleaned_data["email"]
        user = get_user_model().objects.filter(email=email, is_job_seeker=True).first()
        return user


class CreateJobSeekerForm(forms.ModelForm):
    def __init__(self, proxy_user, *args, **kwargs):
        self.proxy_user = proxy_user
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["birthdate"].required = True
        self.fields["birthdate"].input_formats = settings.DATE_INPUT_FORMATS

    class Meta:
        model = get_user_model()
        fields = ["email", "first_name", "last_name", "birthdate", "phone"]
        help_texts = {
            "birthdate": _("Au format jj/mm/aaaa, par exemple 20/12/1978"),
            "phone": _("Par exemple 0610203040"),
        }

    def save(self, commit=True):
        if commit:
            return self._meta.model.create_job_seeker_by_proxy(
                self.proxy_user, **self.cleaned_data
            )
        return super().save(commit=False)


class SubmitJobApplicationForm(forms.ModelForm):
    """
    Submit a job application to an SIAE.
    """

    def __init__(self, siae, *args, **kwargs):
        self.siae = siae
        super().__init__(*args, **kwargs)
        self.fields["jobs"].queryset = siae.jobs.filter(
            siaejobdescription__is_active=True
        )
        self.fields["message"].required = True

    class Meta:
        model = JobApplication
        fields = ["jobs", "message"]
        widgets = {"jobs": forms.CheckboxSelectMultiple()}
        labels = {"jobs": _("Métiers recherchés (optionnel)")}


class RefusalForm(forms.Form):
    """
    Allow an SIAE to specify a reason for refusal.
    """

    refusal_reason = forms.ChoiceField(
        label=_("Motif du refus"),
        widget=forms.RadioSelect,
        choices=JobApplication.REFUSAL_REASON_CHOICES,
        required=False,
    )
    answer = forms.CharField(
        label=_("Réponse"), widget=forms.Textarea(), required=False, strip=True
    )

    def clean_answer(self):
        answer = self.cleaned_data["answer"]
        refusal_reason = self.cleaned_data["refusal_reason"]
        if refusal_reason == JobApplication.REFUSAL_REASON_OTHER and not answer:
            error = _("Vous devez préciser votre motif de refus.")
            raise forms.ValidationError(error)
        return answer


class AnswerForm(forms.Form):
    """
    Allow an SIAE to add an answer message when postponing or accepting.
    """

    answer = forms.CharField(
        label=_("Réponse"), widget=forms.Textarea(), required=False, strip=True
    )
