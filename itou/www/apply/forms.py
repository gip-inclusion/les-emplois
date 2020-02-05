import datetime

from dateutil.relativedelta import relativedelta

from django import forms
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from itou.approvals.models import Approval
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.widgets import DatePickerField


class UserExistsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None

    email = forms.EmailField(label=_("E-mail du candidat"))

    def clean_email(self):
        email = self.cleaned_data["email"]
        self.user = get_user_model().objects.filter(email__iexact=email).first()
        if self.user:
            if not self.user.is_active:
                error = _(
                    "Vous ne pouvez pas postuler pour cet utilisateur car son compte a été désactivé."
                )
                raise forms.ValidationError(error)
            if not self.user.is_job_seeker:
                error = _(
                    "Vous ne pouvez pas postuler pour cet utilisateur car il n'est pas demandeur d'emploi."
                )
                raise forms.ValidationError(error)
        return email

    def get_user(self):
        return self.user


class CheckJobSeekerInfoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].required = True
        self.fields["birthdate"].input_formats = settings.DATE_INPUT_FORMATS

    class Meta:
        model = get_user_model()
        fields = [
            "birthdate",
            "phone",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
        ]
        help_texts = {
            "birthdate": _("Au format jj/mm/aaaa, par exemple 20/12/1978."),
            "phone": _("Par exemple 0610203040."),
        }

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(
            self.cleaned_data["pole_emploi_id"],
            self.cleaned_data["lack_of_pole_emploi_id_reason"],
        )


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
        fields = [
            "email",
            "first_name",
            "last_name",
            "birthdate",
            "phone",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
        ]
        help_texts = {
            "birthdate": _("Au format jj/mm/aaaa, par exemple 20/12/1978."),
            "phone": _("Par exemple 0610203040."),
        }

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(
            self.cleaned_data["pole_emploi_id"],
            self.cleaned_data["lack_of_pole_emploi_id_reason"],
        )

    def save(self, commit=True):
        if commit:
            return self._meta.model.create_job_seeker_by_proxy(
                self.proxy_user, **self.cleaned_data
            )
        super().save(commit=False)


class SubmitJobApplicationForm(forms.ModelForm):
    """
    Submit a job application to an SIAE.
    """

    def __init__(self, siae, *args, **kwargs):
        self.siae = siae
        super().__init__(*args, **kwargs)
        self.fields["selected_jobs"].queryset = siae.job_description_through.filter(
            is_active=True
        )
        self.fields["message"].required = True

    class Meta:
        model = JobApplication
        fields = ["selected_jobs", "message"]
        widgets = {"selected_jobs": forms.CheckboxSelectMultiple()}
        labels = {"selected_jobs": _("Métiers recherchés (optionnel)")}


class RefusalForm(forms.Form):
    """
    Allow an SIAE to specify a reason for refusal.
    """

    ANSWER_INITIAL = _(
        "Nous avons étudié votre candidature avec la plus grande attention mais "
        "nous sommes au regret de vous informer que celle-ci n'a pas été retenue.\n\n"
        "Soyez assuré que cette décision ne met pas en cause vos qualités personnelles. "
        "Nous sommes très sensibles à l'intérêt que vous portez à notre entreprise, "
        "et conservons vos coordonnées afin de vous recontacter au besoin.\n\n"
        "Nous vous souhaitons une pleine réussite dans vos recherches futures."
    )

    refusal_reason = forms.ChoiceField(
        label=_("Motif du refus (ne sera pas envoyé au candidat)"),
        widget=forms.RadioSelect,
        choices=JobApplication.REFUSAL_REASON_CHOICES,
    )
    answer = forms.CharField(
        label=_("Réponse envoyée au candidat"),
        widget=forms.Textarea(),
        strip=True,
        initial=ANSWER_INITIAL,
        help_text=_("Vous pouvez modifier le texte proposé ou l'utiliser tel quel."),
    )


class AnswerForm(forms.Form):
    """
    Allow an SIAE to add an answer message when postponing or accepting.
    """

    answer = forms.CharField(
        label=_("Réponse"), widget=forms.Textarea(), required=False, strip=True
    )


class AcceptForm(forms.ModelForm):
    """
    Allow an SIAE to add an answer message when postponing or accepting.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ["hiring_start_at", "hiring_end_at"]:
            self.fields[field].required = True
            self.fields[field].input_formats = settings.DATE_INPUT_FORMATS

    class Meta:
        model = JobApplication
        fields = ["hiring_start_at", "hiring_end_at", "answer"]
        help_texts = {
            "hiring_start_at": _("Au format jj/mm/aaaa, par exemple  %(date)s.")
            % {"date": datetime.date.today().strftime("%d/%m/%Y")},
            "hiring_end_at": _("Au format jj/mm/aaaa, par exemple  %(date)s.")
            % {
                "date": (
                    datetime.date.today()
                    + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
                ).strftime("%d/%m/%Y")
            },
        }

    def clean_hiring_start_at(self):
        hiring_start_at = self.cleaned_data["hiring_start_at"]
        if hiring_start_at and hiring_start_at < datetime.date.today():
            raise forms.ValidationError(JobApplication.ERROR_START_IN_PAST)
        return hiring_start_at

    def clean(self):
        cleaned_data = super().clean()

        if self.errors:
            return cleaned_data

        hiring_start_at = self.cleaned_data["hiring_start_at"]
        hiring_end_at = self.cleaned_data["hiring_end_at"]

        if hiring_end_at <= hiring_start_at:
            raise forms.ValidationError(JobApplication.ERROR_END_IS_BEFORE_START)

        if self.instance.to_siae.is_subject_to_eligibility_rules:
            duration = relativedelta(hiring_end_at, hiring_start_at)
            benchmark = Approval.DEFAULT_APPROVAL_YEARS
            if duration.years > benchmark or (
                duration.years == benchmark and duration.days > 0
            ):
                raise forms.ValidationError(JobApplication.ERROR_DURATION_TOO_LONG)

        return cleaned_data


class FilterJobApplicationsForm(forms.Form):
    """
    Allow users to filter job applications based on specific fields.
    """

    states = forms.MultipleChoiceField(
        required=False,
        choices=JobApplicationWorkflow.STATE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    start_date = forms.DateField(
        input_formats=[DatePickerField.DATE_FORMAT],
        label=_("Début"),
        required=False,
        widget=DatePickerField(),
    )
    end_date = forms.DateField(
        input_formats=[DatePickerField.DATE_FORMAT],
        label=_("Fin"),
        required=False,
        widget=DatePickerField(),
    )

    def clean_start_date(self):
        """
        When a start_date does not include time values,
        consider that it means "the whole day".
        Therefore, start_date time should be 0 am.
        """
        start_date = self.cleaned_data.get("start_date")
        if start_date:
            start_date = datetime.datetime.combine(start_date, datetime.time())
            start_date = timezone.make_aware(start_date)
        return start_date

    def clean_end_date(self):
        """
        When an end_date does not include time values,
        consider that it means "the whole day".
        Therefore, end_date time should be 23.59 pm.
        """
        end_date = self.cleaned_data.get("end_date")
        if end_date:
            end_date = datetime.datetime.combine(
                end_date, datetime.time(hour=23, minute=59, second=59)
            )
            end_date = timezone.make_aware(end_date)
        return end_date

    def get_qs_filters(self):
        """
        Get filters to be applied to a query set.
        """
        filters = {}
        data = self.cleaned_data

        if data.get("states"):
            filters["state__in"] = data.get("states")
        if data.get("start_date"):
            filters["created_at__gte"] = data.get("start_date")
        if data.get("end_date"):
            filters["created_at__lte"] = data.get("end_date")

        return filters

    def humanize_filters(self):
        """
        Return active filters to be displayed in a template.
        """
        start_date = self.cleaned_data.get("start_date")
        end_date = self.cleaned_data.get("end_date")
        states = self.cleaned_data.get("states")
        active_filters = []

        if start_date:
            label = FilterJobApplicationsForm.base_fields.get("start_date").label
            active_filters.append([label, start_date])

        if end_date:
            label = FilterJobApplicationsForm.base_fields.get("end_date").label
            active_filters.append([label, end_date])

        if states:
            values = [
                str(JobApplicationWorkflow.states[state].title) for state in states
            ]
            value = ", ".join(values)
            label = _("Statuts") if (len(values) > 1) else _("Statut")
            active_filters.append([label, value])

        return [{"label": f[0], "value": f[1]} for f in active_filters]
