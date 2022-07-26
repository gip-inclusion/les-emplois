import contextlib
import datetime

from dateutil.relativedelta import relativedelta
from django import forms
from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db.models import Q
from django.utils import timezone
from django.utils.safestring import mark_safe
from django_select2.forms import Select2MultipleWidget

from itou.approvals.models import Approval
from itou.asp import models as asp_models
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, department_from_postcode
from itou.common_apps.address.forms import MandatoryAddressFormMixin
from itou.common_apps.resume.forms import ResumeFormMixin
from itou.eligibility.models import AdministrativeCriteria
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.models import JobSeekerProfile, User
from itou.utils.validators import validate_nir, validate_pole_emploi_id
from itou.utils.widgets import DuetDatePickerWidget


class UserExistsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None

    email = forms.EmailField(
        label="E-mail personnel du candidat",
        widget=forms.EmailInput(attrs={"autocomplete": "off", "placeholder": "julie@example.com"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        self.user = User.objects.filter(email__iexact=email).first()
        if self.user:
            if not self.user.is_active:
                error = "Vous ne pouvez pas postuler pour cet utilisateur car son compte a été désactivé."
                raise forms.ValidationError(error)
            if not self.user.is_job_seeker:
                error = "Vous ne pouvez pas postuler pour cet utilisateur car il n'est pas demandeur d'emploi."
                raise forms.ValidationError(error)
        return email

    def get_user(self):
        return self.user


class CheckJobSeekerNirForm(forms.Form):
    nir = forms.CharField(
        label="Numéro de sécurité sociale",
        max_length=21,  # 15 + 6 white spaces
        required=True,
        strip=True,
        validators=[validate_nir],
        widget=forms.TextInput(
            attrs={
                "placeholder": "2 69 05 49 588 157 80",
            }
        ),
    )

    def __init__(self, *args, job_seeker=None, **kwargs):
        self.job_seeker = job_seeker
        super().__init__(*args, **kwargs)
        if self.job_seeker:
            self.fields["nir"].label = "Votre numéro de sécurité sociale"
        else:
            self.fields["nir"].label = "Numéro de sécurité sociale du candidat"

    def clean_nir(self):
        nir = self.cleaned_data["nir"].upper()
        nir = nir.replace(" ", "")
        existing_account = User.objects.filter(nir=nir).first()

        # Job application sent by autonomous job seeker.
        if self.job_seeker:
            if existing_account:
                error_message = (
                    "Ce numéro de sécurité sociale est déjà utilisé par un autre compte. "
                    f"Merci de vous reconnecter avec l'adresse e-mail <b>{existing_account.email}</b>. "
                    "Si vous ne vous souvenez plus de votre mot de passe, vous pourrez "
                    "cliquer sur « mot de passe oublié ». "
                    f'En cas de souci, vous pouvez <a href="{settings.ITOU_ASSISTANCE_URL}" rel="noopener" '
                    'target="_blank" aria-label="Ouverture dans un nouvel onglet">nous contacter</a>.'
                )
                raise forms.ValidationError(mark_safe(error_message))
        else:
            # For the moment, consider NIR to be unique among users.
            self.job_seeker = existing_account
        return nir

    def get_job_seeker(self):
        return self.job_seeker


class CheckJobSeekerInfoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].required = True
        self.fields["birthdate"].widget = DuetDatePickerWidget(
            {
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )

    class Meta:
        model = User
        fields = ["birthdate", "phone", "pole_emploi_id", "lack_of_pole_emploi_id_reason"]
        help_texts = {
            "birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978.",
            "phone": "Par exemple 0610203040.",
        }

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(self.cleaned_data)


class CreateJobSeekerStep1ForSenderForm(forms.ModelForm):

    REQUIRED_FIELDS = [
        "title",
        "first_name",
        "last_name",
        "birthdate",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.REQUIRED_FIELDS:
            self.fields[field_name].required = True

        self.fields["birthdate"].widget = DuetDatePickerWidget(
            {
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
                "class": "js-period-date-input",
            }
        )

    class Meta:
        model = User
        fields = [
            "title",
            "first_name",
            "last_name",
            "birthdate",
        ]


class CreateJobSeekerStep2ForSenderForm(MandatoryAddressFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initial value are overridden in OptionalAddressFormMixin() because we have a model instance,
        # but that instance is always empty in our case so force the value to the one we have.
        with contextlib.suppress(KeyError, City.DoesNotExist):
            city = City.objects.get(slug=kwargs["initial"]["city_slug"])
            self.initial["city"] = city.display_name
            self.initial["city_slug"] = city.slug

    def clean(self):
        super().clean()

        if self.cleaned_data["post_code"]:
            self.cleaned_data["department"] = department_from_postcode(self.cleaned_data["post_code"])

    class Meta:
        model = User
        fields = ["address_line_1", "address_line_2", "post_code", "city_slug", "city", "phone"]


class CreateJobSeekerStep3ForSenderForm(forms.ModelForm):

    # A set of transient checkboxes used to collapse optional blocks
    pole_emploi = forms.BooleanField(required=False, label="Inscrit à Pôle emploi")
    unemployed = forms.BooleanField(required=False, label="Sans emploi")
    rsa_allocation = forms.BooleanField(required=False, label="Bénéficiaire du RSA")
    ass_allocation = forms.BooleanField(required=False, label="Bénéficiaire de l'ASS")
    aah_allocation = forms.BooleanField(required=False, label="Bénéficiaire de l'AAH")

    # Fields from the User model
    pole_emploi_id_forgotten = forms.BooleanField(required=False, label="Identifiant Pôle emploi oublié")
    pole_emploi_id = forms.CharField(
        label="Identifiant Pôle emploi",
        required=False,
        validators=[validate_pole_emploi_id, MinLengthValidator(8)],
    )

    # This field is a subset of the possible choices of `has_rsa_allocation` model field
    has_rsa_allocation = forms.ChoiceField(
        required=False, label="Majoration du RSA", choices=asp_models.RSAAllocation.choices[1:]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["education_level"].required = True
        self.fields["education_level"].label = "Niveau de formation"

    def clean(self):
        super().clean()

        # Handle the 'since' fields, which is most of them.
        collapsible_errors = {
            "pole_emploi": "La durée d'inscription à Pôle emploi est obligatoire",
            "unemployed": "La période sans emploi est obligatoire",
            "rsa_allocation": "La durée d'allocation du RSA est obligatoire",
            "ass_allocation": "La durée d'allocation de l'ASS est obligatoire",
            "aah_allocation": "La durée d'allocation de l'AAH est obligatoire",
        }

        for collapsible_field, error_message in collapsible_errors.items():
            inner_field_name = collapsible_field + "_since"
            if self.cleaned_data[collapsible_field]:
                if not self.cleaned_data[inner_field_name]:
                    self.add_error(inner_field_name, forms.ValidationError(error_message))
            else:
                # Reset "inner" model fields, if non-model field unchecked
                self.cleaned_data[inner_field_name] = ""

        # Handle Pole Emploi extra fields
        if self.cleaned_data["pole_emploi"]:
            if self.cleaned_data["pole_emploi_id_forgotten"]:
                self.cleaned_data["lack_of_pole_emploi_id_reason"] = User.REASON_FORGOTTEN
                self.cleaned_data["pole_emploi_id"] = ""
            elif self.cleaned_data.get("pole_emploi_id"):
                self.cleaned_data["lack_of_pole_emploi_id_reason"] = ""
            elif not self.cleaned_data.get("pole_emploi_id") and not self.has_error("pole_emploi_id"):
                # The 'pole_emploi_id' field is missing when its validation fails,
                # also don't stack a 'missing field' error if an error already exists ('wrong format' in this case)
                self.add_error("pole_emploi_id", forms.ValidationError("L'identifiant Pôle emploi est obligatoire"))
        else:
            self.cleaned_data["pole_emploi_id_forgotten"] = ""
            self.cleaned_data["pole_emploi_id"] = ""
            self.cleaned_data["lack_of_pole_emploi_id_reason"] = User.REASON_NOT_REGISTERED

        # Handle RSA extra fields
        if self.cleaned_data["rsa_allocation"]:
            if not self.cleaned_data["has_rsa_allocation"]:
                self.add_error("has_rsa_allocation", forms.ValidationError("La majoration RSA est obligatoire"))
        else:
            self.cleaned_data["has_rsa_allocation"] = asp_models.RSAAllocation.NO

    class Meta:
        model = JobSeekerProfile
        fields = [
            "education_level",
            "resourceless",
            "pole_emploi_since",
            "unemployed_since",
            "rqth_employee",
            "oeth_employee",
            "has_rsa_allocation",
            "rsa_allocation_since",
            "ass_allocation_since",
            "aah_allocation_since",
        ]


class SubmitJobApplicationForm(forms.ModelForm, ResumeFormMixin):
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
        fields = ["selected_jobs", "message"] + ResumeFormMixin.Meta.fields
        widgets = {
            "selected_jobs": forms.CheckboxSelectMultiple(),
            "message": forms.Textarea(
                attrs={
                    "placeholder": (
                        "Message à destination de l’employeur (avec copie transmise au candidat)"
                        " et non modifiable après l’envoi : motivations du candidat, motifs d’orientation, "
                        "éléments du diagnostic socio-professionnel, ..."
                    )
                }
            ),
        }
        labels = {"selected_jobs": "Métiers recherchés (ne rien cocher pour une candidature spontanée)"}


class RefusalForm(forms.Form):
    """
    Allow an SIAE to specify a reason for refusal.
    """

    ANSWER_INITIAL = (
        "Nous avons étudié votre candidature avec la plus grande attention mais "
        "nous sommes au regret de vous informer que celle-ci n'a pas été retenue.\n\n"
        "Soyez assuré que cette décision ne met pas en cause vos qualités personnelles. "
        "Nous sommes très sensibles à l'intérêt que vous portez à notre entreprise, "
        "et conservons vos coordonnées afin de vous recontacter au besoin.\n\n"
        "Nous vous souhaitons une pleine réussite dans vos recherches futures."
    )

    refusal_reason = forms.ChoiceField(
        label="Sélectionner un motif de refus (n'est pas envoyé au candidat)",
        widget=forms.RadioSelect,
        choices=job_applications_enums.RefusalReason.displayed_choices(),
    )
    answer = forms.CharField(
        label="Message à envoyer au candidat (une copie sera envoyée au prescripteur)",
        widget=forms.Textarea(),
        strip=True,
        initial=ANSWER_INITIAL,
        help_text="Vous pouvez modifier le texte proposé ou l'utiliser tel quel.",
    )
    answer_to_prescriber = forms.CharField(
        label="Commentaire privé à destination du prescripteur (n'est pas envoyé au candidat)",
        widget=forms.Textarea(attrs={"placeholder": ""}),
        strip=True,
        required=False,
    )

    def __init__(self, job_application, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if job_application.sender_kind != job_applications_enums.SenderKind.PRESCRIBER:
            self.fields.pop("answer_to_prescriber")
            self.fields["answer"].label = "Message à envoyer au candidat"


class AnswerForm(forms.Form):
    """
    Allow an SIAE to add an answer message when postponing or accepting.
    """

    answer = forms.CharField(
        label="Réponse",
        widget=forms.Textarea(attrs={"placeholder": "Votre réponse sera visible par le candidat et le prescripteur"}),
        required=False,
        strip=True,
    )


class AcceptForm(forms.ModelForm):
    """
    Allow an SIAE to add an answer message when postponing or accepting.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hiring_start_at"].required = True
        for field in ["hiring_start_at", "hiring_end_at"]:
            self.fields[field].widget = DuetDatePickerWidget()
        # Job applications can be accepted twice if they have been cancelled.
        # They also can be accepted after a refusal.
        # That's why some fields are already filled in with obsolete data.
        # Erase them now to start from new.
        for field in ["answer", "hiring_start_at", "hiring_end_at"]:
            self.initial[field] = ""

    class Meta:
        model = JobApplication
        fields = ["hiring_start_at", "hiring_end_at", "answer"]
        help_texts = {
            # Make it clear to employers that `hiring_start_at` has an impact on the start of the
            # "parcours IAE" and the payment of the "aide au poste".
            "hiring_start_at": (
                "Au format JJ/MM/AAAA, par exemple  %(date)s. Il n'est pas possible d'antidater un contrat. "
                "La date est modifiable jusqu'à la veille de la date saisie. En cas de premier PASS IAE pour "
                "la personne, cette date déclenche le début de son parcours."
            )
            % {"date": datetime.date.today().strftime("%d/%m/%Y")},
            "hiring_end_at": (
                "Au format JJ/MM/AAAA, par exemple  %(date)s. "
                "Elle sert uniquement à des fins d'informations et est sans conséquence sur les déclarations "
                "à faire dans l'extranet 2.0 de l'ASP. "
                "<b>Ne pas compléter cette date dans le cadre d’un CDI Inclusion</b>"
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

        if hiring_end_at and hiring_end_at < hiring_start_at:
            raise forms.ValidationError(JobApplication.ERROR_END_IS_BEFORE_START)

        return cleaned_data


class EditHiringDateForm(forms.ModelForm):
    """
    Allows a SIAE to change contract date (if current one is in the future)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hiring_start_at"].required = True
        for field in ["hiring_start_at", "hiring_end_at"]:
            self.fields[field].widget = DuetDatePickerWidget()

    class Meta:
        model = JobApplication
        fields = ["hiring_start_at", "hiring_end_at"]
        help_texts = {
            "hiring_start_at": (
                "Il n'est pas possible d'antidater un contrat. "
                "Indiquez une date dans le futur. "
                "Cette date peut-être repoussée de 30 jours au plus, "
                "et avant la fin du PASS IAE éventuellement émis pour cette candidature."
            ),
            "hiring_end_at": (
                "Cette date sert uniquement à des fins d'informations et est sans conséquence"
                " sur les déclarations à faire dans l'extranet 2.0 de l'ASP. "
                "<b>Ne pas compléter cette date dans le cadre d’un CDI Inclusion</b>"
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

        if hiring_end_at and hiring_end_at < hiring_start_at:
            raise forms.ValidationError(JobApplication.ERROR_END_IS_BEFORE_START)

        # Check if hiring date is before end of a possible "old" approval
        approval = self.instance.approval

        if approval and not approval.can_postpone_start_date:
            if hiring_start_at >= approval.end_at:
                raise forms.ValidationError(JobApplication.ERROR_START_AFTER_APPROVAL_END)

        return cleaned_data


class JobSeekerPoleEmploiStatusForm(forms.ModelForm):
    """
    Info that will be used to search for an existing Pôle emploi approval.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].widget = DuetDatePickerWidget(
            attrs={
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )

    class Meta:
        model = User
        fields = ["birthdate", "pole_emploi_id", "lack_of_pole_emploi_id_reason"]
        help_texts = {"birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978."}

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(self.cleaned_data)


class UserAddressForm(MandatoryAddressFormMixin, forms.ModelForm):
    """
    Add job seeker address in the job application process.
    """

    class Meta:
        model = User
        fields = ["address_line_1", "address_line_2", "post_code", "city_slug", "city"]


class FilterJobApplicationsForm(forms.Form):
    """
    Allow users to filter job applications based on specific fields.
    """

    states = forms.MultipleChoiceField(
        required=False, choices=JobApplicationWorkflow.STATE_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    start_date = forms.DateField(
        label="À partir du",
        required=False,
        widget=DuetDatePickerWidget(),
    )
    end_date = forms.DateField(
        label="Jusqu'au",
        required=False,
        widget=DuetDatePickerWidget(),
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
        if data.get("pass_iae_active"):
            filters["has_active_approval"] = True
        if data.get("eligibility_validated"):
            filters["last_jobseeker_eligibility_diagnosis__isnull"] = False
        if data.get("start_date"):
            filters["created_at__gte"] = data.get("start_date")
        if data.get("end_date"):
            filters["created_at__lte"] = data.get("end_date")
        if data.get("departments"):
            filters["job_seeker__department__in"] = data.get("departments")
        if data.get("selected_jobs"):
            filters["selected_jobs__appellation__code__in"] = data.get("selected_jobs")
        if data.get("criteria"):
            # Filter on the `last_eligibility_diagnosis_criterion_{criterion}` annotation,
            # which is set in `with_list_related_data()`.
            for criterion in data.get("criteria"):
                filters[f"last_eligibility_diagnosis_criterion_{criterion}"] = True

        filters = [Q(**filters)]

        return filters

    def get_qs_filters_counter(self, qs_filters):
        """
        Get number of filters to be applied to a query set.
        """
        filters_counter = 0
        for qs_filter in qs_filters:
            for filters in qs_filter.children:
                filters_counter += len(filters[1]) if type(filters[1]) is list else 1

        return filters_counter


class SiaePrescriberFilterJobApplicationsForm(FilterJobApplicationsForm):
    """
    Job applications filters common to SIAE and Prescribers.
    """

    senders = forms.MultipleChoiceField(required=False, label="Nom de la personne", widget=Select2MultipleWidget)

    job_seekers = forms.MultipleChoiceField(required=False, label="Nom du candidat", widget=Select2MultipleWidget)

    pass_iae_suspended = forms.BooleanField(label="PASS IAE suspendu", required=False)
    pass_iae_active = forms.BooleanField(label="PASS IAE actif", required=False)
    criteria = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    eligibility_validated = forms.BooleanField(label="Éligibilité validée", required=False)
    departments = forms.MultipleChoiceField(
        required=False, label="Département du candidat", widget=forms.CheckboxSelectMultiple
    )
    selected_jobs = forms.MultipleChoiceField(
        required=False, label="Fiches de poste", widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, job_applications_qs, *args, **kwargs):
        self.job_applications_qs = job_applications_qs
        super().__init__(*args, **kwargs)
        self.fields["senders"].choices += self._get_choices_for("sender")
        self.fields["job_seekers"].choices = self._get_choices_for("job_seeker")
        self.fields["criteria"].choices = self._get_choices_for_administrativecriteria()
        self.fields["departments"].choices = self._get_choices_for_departments()
        self.fields["selected_jobs"].choices = self._get_choices_for_jobs()

    def _get_choices_for(self, user_type):
        users = self.job_applications_qs.get_unique_fk_objects(user_type)
        users = [user for user in users if user.get_full_name()]
        users = [(user.id, user.get_full_name().title()) for user in users]
        return sorted(users, key=lambda l: l[1])

    def _get_choices_for_administrativecriteria(self):
        return [(c.pk, c.name) for c in AdministrativeCriteria.objects.all()]

    def _get_choices_for_departments(self):
        job_seekers = self.job_applications_qs.get_unique_fk_objects("job_seeker")
        departments = {
            (user.department, DEPARTMENTS.get(user.department))
            for user in job_seekers
            if user.department in DEPARTMENTS
        }
        return sorted(departments, key=lambda l: l[1])

    def _get_choices_for_jobs(self):
        jobs = set()
        for job_application in self.job_applications_qs.prefetch_related("selected_jobs__appellation"):
            for job in job_application.selected_jobs.all():
                jobs.add((job.appellation.code, job.appellation.name))
        return sorted(jobs, key=lambda l: l[1])

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


class SiaeFilterJobApplicationsForm(SiaePrescriberFilterJobApplicationsForm):
    """
    Job applications filters for SIAE only.
    """

    sender_organizations = forms.MultipleChoiceField(
        required=False, label="Nom de l'organisme prescripteur", widget=Select2MultipleWidget
    )

    def __init__(self, job_applications_qs, siae, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["sender_organizations"].choices += self.get_sender_organization_choices()

        if siae.kind not in siae.ELIGIBILITY_REQUIRED_KINDS:
            del self.fields["eligibility_validated"]

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


class PrescriberFilterJobApplicationsForm(SiaePrescriberFilterJobApplicationsForm):
    """
    Job applications filters for Prescribers only.
    """

    to_siaes = forms.MultipleChoiceField(required=False, label="Structure", widget=Select2MultipleWidget)

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
