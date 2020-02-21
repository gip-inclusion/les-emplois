import datetime

from django import forms
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from itou.users.models import User
from itou.prescribers.models import PrescriberOrganization
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
        fields = ["birthdate", "phone"]
        help_texts = {
            "birthdate": _("Au format jj/mm/aaaa, par exemple 20/12/1978"),
            "phone": _("Par exemple 0610203040"),
        }


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
        self.fields["date_of_hiring"].required = True
        self.fields["date_of_hiring"].input_formats = settings.DATE_INPUT_FORMATS

    class Meta:
        model = JobApplication
        fields = ["date_of_hiring", "answer"]
        help_texts = {
            "date_of_hiring": _("Au format jj/mm/aaaa, par exemple  %(date)s.")
            % {"date": datetime.date.today().strftime("%d/%m/%Y")}
        }

    def clean_date_of_hiring(self):
        date_of_hiring = self.cleaned_data["date_of_hiring"]
        if date_of_hiring and date_of_hiring < datetime.date.today():
            error = _("La date d'embauche ne doit pas être dans le passé.")
            raise forms.ValidationError(error)
        return date_of_hiring


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

        filters = [Q(**filters)]

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
            label = self.base_fields.get("start_date").label
            active_filters.append([label, start_date])

        if end_date:
            label = self.base_fields.get("end_date").label
            active_filters.append([label, end_date])

        if states:
            values = [
                str(JobApplicationWorkflow.states[state].title) for state in states
            ]
            value = ", ".join(values)
            label = _("Statuts") if (len(values) > 1) else _("Statut")
            active_filters.append([label, value])

        return [{"label": f[0], "value": f[1]} for f in active_filters]


class SiaePrescriberFilterJobApplicationsForm(FilterJobApplicationsForm):
    """
    Job applications filters common to SIAE and Prescribers.
    """

    sender = forms.ChoiceField(
        required=False, label=_("Personne"), choices=[("", "-" * 50)]
    )

    def __init__(self, job_applications_qs, *args, **kwargs):
        self.job_applications_qs = job_applications_qs
        super().__init__(*args, **kwargs)
        self.fields["sender"].choices += self.get_sender_choices()

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        data = self.cleaned_data
        sender = data.get("sender")

        if sender:
            qs = Q(sender__id=sender)
            qs_list.append(qs)

        return qs_list

    def get_sender_choices(self):
        senders = self.job_applications_qs.get_unique_fk_objects("sender")
        senders = [sender for sender in senders if sender.get_full_name()]
        senders = [(sender.id, sender.get_full_name().title()) for sender in senders]
        return sorted(senders, key=lambda l: l[1])

    def humanize_filters(self):
        humanized_filters = super().humanize_filters()
        sender = self.cleaned_data.get("sender")

        if sender:
            label = self.base_fields.get("sender").label
            user = User.objects.get(id=int(sender))
            value = user.get_full_name().title()
            humanized_filters.append({"label": label, "value": value})

        return humanized_filters


class SiaeFilterJobApplicationsForm(SiaePrescriberFilterJobApplicationsForm):
    """
    Job applications filters for SIAE only.
    """

    sender_organization = forms.ChoiceField(
        required=False, label=_("Organisation"), choices=[("", "-" * 50)]
    )

    def __init__(self, job_applications_qs, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields[
            "sender_organization"
        ].choices += self.get_sender_organization_choices()

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        data = self.cleaned_data
        sender_organization = data.get("sender_organization")

        if sender_organization:
            qs = Q(sender_prescriber_organization__id=sender_organization)
            qs_list.append(qs)

        return qs_list

    def get_sender_organization_choices(self):
        sender_orgs = self.job_applications_qs.get_unique_fk_objects(
            "sender_prescriber_organization"
        )
        sender_orgs = [sender for sender in sender_orgs if sender.name]
        sender_orgs = [(sender.id, sender.name.title()) for sender in sender_orgs]
        return sorted(sender_orgs, key=lambda l: l[1])

    def humanize_filters(self):
        humanized_filters = super().humanize_filters()
        sender_organization = self.cleaned_data.get("sender_organization")

        if sender_organization:
            label = self.base_fields.get("sender_organization").label
            organization = PrescriberOrganization.objects.get(
                id=int(sender_organization)
            )
            value = organization.name.title()
            humanized_filters.append({"label": label, "value": value})

        return humanized_filters


class PrescriberFilterJobApplicationsForm(SiaePrescriberFilterJobApplicationsForm):
    """
    Job applications filters for Prescribers only.
    """

    # pylint: disable=unnecessary-pass
    pass
