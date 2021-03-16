import datetime

from dateutil.relativedelta import relativedelta
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy
from django_select2.forms import Select2MultipleWidget

from itou.approvals.models import Approval
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.address.forms import AddressFormMixin
from itou.utils.resume.forms import ResumeFormMixin
from itou.utils.widgets import DatePickerField


class UserExistsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None

    email = forms.EmailField(
        label=gettext_lazy("E-mail personnel du candidat"), widget=forms.TextInput(attrs={"autocomplete": "off"})
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        self.user = get_user_model().objects.filter(email__iexact=email).first()
        if self.user:
            if not self.user.is_active:
                error = _("Vous ne pouvez pas postuler pour cet utilisateur car son compte a été désactivé.")
                raise forms.ValidationError(error)
            if not self.user.is_job_seeker:
                error = _("Vous ne pouvez pas postuler pour cet utilisateur car il n'est pas demandeur d'emploi.")
                raise forms.ValidationError(error)
        return email

    def get_user(self):
        return self.user


class CheckJobSeekerInfoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].required = True
        self.fields["birthdate"].widget = DatePickerField(
            {
                "viewMode": "years",
                "minDate": DatePickerField.min_birthdate().strftime("%Y/%m/%d"),
                "maxDate": DatePickerField.max_birthdate().strftime("%Y/%m/%d"),
            }
        )
        self.fields["birthdate"].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = get_user_model()
        fields = ["birthdate", "phone", "pole_emploi_id", "lack_of_pole_emploi_id_reason"]
        help_texts = {
            "birthdate": gettext_lazy("Au format JJ/MM/AAAA, par exemple 20/12/1978."),
            "phone": gettext_lazy("Par exemple 0610203040."),
        }

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(
            self.cleaned_data["pole_emploi_id"], self.cleaned_data["lack_of_pole_emploi_id_reason"]
        )


class CreateJobSeekerForm(AddressFormMixin, ResumeFormMixin, forms.ModelForm):
    def __init__(self, proxy_user, *args, **kwargs):
        self.proxy_user = proxy_user
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["email"].widget.attrs["readonly"] = True
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

        # Birth date
        self.fields["birthdate"].required = True
        self.fields["birthdate"].widget = DatePickerField(
            {
                "viewMode": "years",
                "minDate": DatePickerField.min_birthdate().strftime("%Y/%m/%d"),
                "maxDate": DatePickerField.max_birthdate().strftime("%Y/%m/%d"),
                "useCurrent": False,
                "allowInputToggle": False,
            }
        )
        self.fields["birthdate"].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = get_user_model()
        fields = [
            "email",
            "first_name",
            "last_name",
            "birthdate",
            "phone",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city_name",
            "city",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
        ] + ResumeFormMixin.Meta.fields
        help_texts = {
            "birthdate": gettext_lazy("Au format JJ/MM/AAAA, par exemple 20/12/1978."),
            "phone": gettext_lazy("Par exemple 0610203040."),
        }

    def clean_email(self):
        email = self.cleaned_data["email"]
        if get_user_model().email_already_exists(email):
            raise forms.ValidationError(get_user_model().ERROR_EMAIL_ALREADY_EXISTS)
        return email

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(
            self.cleaned_data["pole_emploi_id"], self.cleaned_data["lack_of_pole_emploi_id_reason"]
        )

    def save(self, commit=True):
        # Exclude 'city_name' form field (not mapped to model)
        partial_fields = self.cleaned_data
        del partial_fields["city_name"]

        if commit:
            return self._meta.model.create_job_seeker_by_proxy(self.proxy_user, **partial_fields)
        return super().save(commit=False)


class SubmitJobApplicationForm(forms.ModelForm):
    """
    Submit a job application to an SIAE.
    """

    def __init__(self, siae, *args, **kwargs):
        self.siae = siae
        super().__init__(*args, **kwargs)
        self.fields["selected_jobs"].queryset = siae.job_description_through.filter(is_active=True)
        self.fields["message"].required = True

    class Meta:
        model = JobApplication
        fields = ["selected_jobs", "message"]
        widgets = {
            "selected_jobs": forms.CheckboxSelectMultiple(),
            "message": forms.Textarea(
                attrs={
                    "placeholder": gettext_lazy(
                        "Message à destination de l’employeur (avec copie transmise au candidat)"
                        " et non modifiable après l’envoi : motivations du candidat, motifs d’orientation, "
                        "éléments du diagnostic socio-professionnel, ..."
                    )
                }
            ),
        }
        labels = {"selected_jobs": gettext_lazy("Métiers recherchés (optionnel)")}


class RefusalForm(forms.Form):
    """
    Allow an SIAE to specify a reason for refusal.
    """

    ANSWER_INITIAL = gettext_lazy(
        "Nous avons étudié votre candidature avec la plus grande attention mais "
        "nous sommes au regret de vous informer que celle-ci n'a pas été retenue.\n\n"
        "Soyez assuré que cette décision ne met pas en cause vos qualités personnelles. "
        "Nous sommes très sensibles à l'intérêt que vous portez à notre entreprise, "
        "et conservons vos coordonnées afin de vous recontacter au besoin.\n\n"
        "Nous vous souhaitons une pleine réussite dans vos recherches futures."
    )

    refusal_reason = forms.ChoiceField(
        label=gettext_lazy("Motif du refus (ne sera pas envoyé au candidat)"),
        widget=forms.RadioSelect,
        choices=JobApplication.REFUSAL_REASON_CHOICES,
    )
    answer = forms.CharField(
        label=gettext_lazy("Réponse envoyée au candidat"),
        widget=forms.Textarea(),
        strip=True,
        initial=ANSWER_INITIAL,
        help_text=gettext_lazy("Vous pouvez modifier le texte proposé ou l'utiliser tel quel."),
    )


class AnswerForm(forms.Form):
    """
    Allow an SIAE to add an answer message when postponing or accepting.
    """

    answer = forms.CharField(
        label=gettext_lazy("Réponse"),
        widget=forms.Textarea(
            attrs={"placeholder": gettext_lazy("Votre réponse sera visible par le candidat et le prescripteur")}
        ),
        required=False,
        strip=True,
    )


class AcceptForm(forms.ModelForm):
    """
    Allow an SIAE to add an answer message when postponing or accepting.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hiring_without_approval"].widget = forms.HiddenInput()
        for field in ["hiring_start_at", "hiring_end_at"]:
            self.fields[field].required = True
            self.fields[field].widget = DatePickerField()
            self.fields[field].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = JobApplication
        fields = ["hiring_start_at", "hiring_end_at", "answer", "hiring_without_approval"]
        help_texts = {
            "hiring_start_at": gettext_lazy(
                "Au format JJ/MM/AAAA, par exemple  %(date)s. Il n'est pas possible d'antidater un contrat. "
                "Indiquez une date dans le futur."
            )
            % {"date": datetime.date.today().strftime("%d/%m/%Y")},
            "hiring_end_at": gettext_lazy(
                "Au format JJ/MM/AAAA, par exemple  %(date)s. "
                "Elle sert uniquement à des fins d'informations et est sans conséquence sur les déclarations "
                "à faire dans l'extranet 2.0 de l'ASP."
            )
            % {
                "date": (datetime.date.today() + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)).strftime(
                    "%d/%m/%Y"
                )
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

        if hiring_end_at < hiring_start_at:
            raise forms.ValidationError(JobApplication.ERROR_END_IS_BEFORE_START)

        if self.instance.to_siae.is_subject_to_eligibility_rules:
            duration = relativedelta(hiring_end_at, hiring_start_at)
            benchmark = Approval.DEFAULT_APPROVAL_YEARS
            if duration.years > benchmark or (duration.years == benchmark and duration.days > 0):
                raise forms.ValidationError(JobApplication.ERROR_DURATION_TOO_LONG)

        return cleaned_data


class EditHiringDateForm(forms.ModelForm):
    """
    Allows a SIAE to change contract date (if current one is in the future)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ["hiring_start_at", "hiring_end_at"]:
            self.fields[field].required = True
            self.fields[field].widget = DatePickerField()
            self.fields[field].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = JobApplication
        fields = ["hiring_start_at", "hiring_end_at"]
        help_texts = {
            "hiring_start_at": gettext_lazy(
                "Il n'est pas possible d'antidater un contrat. "
                "Indiquez une date dans le futur. "
                "Cette date peut-être repoussée de 30 jours au plus, "
                "et avant la fin du PASS IAE éventuellement émis pour cette candidature."
            ),
            "hiring_end_at": gettext_lazy(
                "Cette date sert uniquement à des fins d'informations et est sans conséquence"
                " sur les déclarations à faire dans l'extranet 2.0 de l'ASP."
            ),
        }

    def clean_hiring_start_at(self):
        hiring_start_at = self.cleaned_data["hiring_start_at"]

        if hiring_start_at < datetime.date.today():
            raise forms.ValidationError(JobApplication.ERROR_START_IN_PAST)

        if hiring_start_at > datetime.date.today() + relativedelta(days=JobApplication.MAX_CONTRACT_POSTPONE_IN_DAYS):
            raise forms.ValidationError(JobApplication.ERROR_POSTPONE_TOO_FAR)

        return hiring_start_at

    def clean(self):
        cleaned_data = super().clean()

        if self.errors:
            return cleaned_data

        hiring_start_at = self.cleaned_data["hiring_start_at"]
        hiring_end_at = self.cleaned_data["hiring_end_at"]

        if hiring_end_at < hiring_start_at:
            raise forms.ValidationError(JobApplication.ERROR_END_IS_BEFORE_START)

        # Check if hiring date is before end of a possible "old" approval
        approval = self.instance.approval

        if approval and not approval.can_postpone_start_date:
            if hiring_start_at >= approval.end_at:
                raise forms.ValidationError(JobApplication.ERROR_START_AFTER_APPROVAL_END)

        return cleaned_data


class JobSeekerPoleEmploiStatusForm(forms.ModelForm):
    """
    Info that will be used to find an existing Pôle emploi approval.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].widget = DatePickerField()
        self.fields["birthdate"].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = get_user_model()
        fields = ["birthdate", "pole_emploi_id", "lack_of_pole_emploi_id_reason"]
        help_texts = {"birthdate": gettext_lazy("Au format JJ/MM/AAAA, par exemple 20/12/1978.")}

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(
            self.cleaned_data["pole_emploi_id"], self.cleaned_data["lack_of_pole_emploi_id_reason"]
        )


class UserAddressForm(AddressFormMixin, forms.ModelForm):
    """
    Add job seeker address in the job application process.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in ["address_line_1", "post_code", "city_name"]:
            self.fields[field].required = True

    class Meta:
        model = get_user_model()
        fields = ["address_line_1", "address_line_2", "post_code", "city_name", "city"]


class FilterJobApplicationsForm(forms.Form):
    """
    Allow users to filter job applications based on specific fields.
    """

    states = forms.MultipleChoiceField(
        required=False, choices=JobApplicationWorkflow.STATE_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    pass_iae_suspended = forms.BooleanField(label=gettext_lazy("PASS IAE suspendu"), required=False)
    start_date = forms.DateField(
        input_formats=[DatePickerField.DATE_FORMAT],
        label=gettext_lazy("Début"),
        required=False,
        widget=DatePickerField(),
    )
    end_date = forms.DateField(
        input_formats=[DatePickerField.DATE_FORMAT],
        label=gettext_lazy("Fin"),
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
            end_date = datetime.datetime.combine(end_date, datetime.time(hour=23, minute=59, second=59))
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
        if data.get("pass_iae_suspended"):
            # Filter on the `has_suspended_approval` annotation, which is set in `with_list_related_data()`.
            filters["has_suspended_approval"] = True
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
            values = [str(JobApplicationWorkflow.states[state].title) for state in states]
            value = ", ".join(values)
            label = _("Statuts") if (len(values) > 1) else _("Statut")
            active_filters.append([label, value])

        return [{"label": f[0], "value": f[1]} for f in active_filters]


class SiaePrescriberFilterJobApplicationsForm(FilterJobApplicationsForm):
    """
    Job applications filters common to SIAE and Prescribers.
    """

    senders = forms.MultipleChoiceField(required=False, label=_("Nom"), widget=Select2MultipleWidget)

    job_seekers = forms.MultipleChoiceField(required=False, label=_("Candidat"), widget=Select2MultipleWidget)

    def __init__(self, job_applications_qs, *args, **kwargs):
        self.job_applications_qs = job_applications_qs
        super().__init__(*args, **kwargs)
        self.fields["senders"].choices += self._get_choices_for("sender")
        self.fields["job_seekers"].choices = self._get_choices_for("job_seeker")

    def _get_choices_for(self, user_type):
        users = self.job_applications_qs.get_unique_fk_objects(user_type)
        users = [user for user in users if user.get_full_name()]
        users = [(user.id, user.get_full_name().title()) for user in users]
        return sorted(users, key=lambda l: l[1])

    def _humanize_multiple_choice_for_users(self, user_ids, field_name):
        users = get_user_model().objects.filter(pk__in=[int(user_id) for user_id in user_ids])
        values = [user.get_full_name().title() for user in users]
        value = ", ".join(values)
        label = self.base_fields.get(field_name).label
        label = f"{label}s" if (len(values) > 1) else label
        return label, value

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        data = self.cleaned_data
        senders = data.get("senders")
        job_seekers = data.get("job_seekers")

        if senders:
            qs = Q(sender__id__in=senders)
            qs_list.append(qs)

        if job_seekers:
            qs = Q(job_seeker__id__in=job_seekers)
            qs_list.append(qs)

        return qs_list

    def humanize_filters(self):
        humanized_filters = super().humanize_filters()
        senders = self.cleaned_data.get("senders")
        job_seekers = self.cleaned_data.get("job_seekers")

        if senders:
            label, value = self._humanize_multiple_choice_for_users(senders, "senders")
            humanized_filters.append({"label": label, "value": value})

        if job_seekers:
            label, value = self._humanize_multiple_choice_for_users(job_seekers, "job_seekers")
            humanized_filters.append({"label": label, "value": value})

        return humanized_filters


class SiaeFilterJobApplicationsForm(SiaePrescriberFilterJobApplicationsForm):
    """
    Job applications filters for SIAE only.
    """

    sender_organizations = forms.MultipleChoiceField(
        required=False, label=_("Prescripteur"), widget=Select2MultipleWidget
    )

    def __init__(self, job_applications_qs, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["sender_organizations"].choices += self.get_sender_organization_choices()

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        data = self.cleaned_data
        sender_organizations = data.get("sender_organizations")

        if sender_organizations:
            qs = Q(sender_prescriber_organization__id__in=sender_organizations)
            qs_list.append(qs)

        return qs_list

    def get_sender_organization_choices(self):
        sender_orgs = self.job_applications_qs.get_unique_fk_objects("sender_prescriber_organization")
        sender_orgs = [sender for sender in sender_orgs if sender.display_name]
        sender_orgs = [(sender.id, sender.display_name.title()) for sender in sender_orgs]
        return sorted(sender_orgs, key=lambda l: l[1])

    def humanize_filters(self):
        humanized_filters = super().humanize_filters()
        sender_organizations = self.cleaned_data.get("sender_organizations")

        if sender_organizations:
            values = [
                PrescriberOrganization.objects.get(pk=int(organization_id)).display_name.title()
                for organization_id in sender_organizations
            ]
            value = ", ".join(values)
            label = self.base_fields.get("sender_organizations").label
            label = f"{label}s" if (len(values) > 1) else label

            humanized_filters.append({"label": label, "value": value})

        return humanized_filters


class PrescriberFilterJobApplicationsForm(SiaePrescriberFilterJobApplicationsForm):
    """
    Job applications filters for Prescribers only.
    """

    to_siaes = forms.MultipleChoiceField(required=False, label=_("Structure"), widget=Select2MultipleWidget)

    def __init__(self, job_applications_qs, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["to_siaes"].choices += self.get_to_siaes_choices()

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        data = self.cleaned_data
        to_siaes = data.get("to_siaes")

        if to_siaes:
            qs = Q(to_siae__id__in=to_siaes)
            qs_list.append(qs)

        return qs_list

    def get_to_siaes_choices(self):
        to_siaes = self.job_applications_qs.get_unique_fk_objects("to_siae")
        to_siaes = [siae for siae in to_siaes if siae.display_name]
        to_siaes = [(siae.id, siae.display_name.title()) for siae in to_siaes]
        return sorted(to_siaes, key=lambda l: l[1])

    def humanize_filters(self):
        humanized_filters = super().humanize_filters()
        to_siaes = self.cleaned_data.get("to_siaes")

        if to_siaes:
            values = [Siae.objects.get(pk=int(siae_pk)).display_name.title() for siae_pk in to_siaes]
            value = ", ".join(values)
            label = self.base_fields.get("to_siaes").label
            label = f"{label}s" if (len(values) > 1) else label

            humanized_filters.append({"label": label, "value": value})

        return humanized_filters
