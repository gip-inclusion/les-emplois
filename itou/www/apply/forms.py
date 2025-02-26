import datetime
import logging
from operator import itemgetter

import sentry_sdk
from dateutil.relativedelta import relativedelta
from django import forms
from django.conf import settings
from django.db.models import Q, TextChoices
from django.db.models.fields import BLANK_CHOICE_DASH
from django.urls import reverse
from django.utils import timezone
from django_select2.forms import Select2MultipleWidget, Select2Widget

from itou.approvals.models import Approval
from itou.common_apps.address.departments import DEPARTMENTS
from itou.common_apps.nir.forms import JobSeekerNIRUpdateMixin
from itou.companies.enums import CompanyKind, ContractType, JobDescriptionSource
from itou.companies.models import JobDescription
from itou.eligibility.models import AdministrativeCriteria
from itou.files.forms import ItouFileField
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, PriorAction
from itou.users.forms import JobSeekerProfileModelForm
from itou.users.models import JobSeekerProfile
from itou.utils import constants as global_constants
from itou.utils.templatetags.str_filters import mask_unless, pluralizefr
from itou.utils.types import InclusiveDateRange
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.companies_views.forms import JobAppellationAndLocationMixin


logger = logging.getLogger(__name__)


class ApplicationJobsForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ["selected_jobs"]
        widgets = {
            "selected_jobs": forms.CheckboxSelectMultiple,
        }

    def __init__(self, company, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["selected_jobs"].queryset = (
            company.job_description_through.active().with_annotation_is_overwhelmed().prefetch_related("appellation")
        )

        if company.is_open_to_spontaneous_applications:
            self.fields["spontaneous_application"] = forms.BooleanField(
                required=False,
                label="Candidature spontanée",
            )

            if not self.initial.get("selected_jobs"):
                self.initial["spontaneous_application"] = True

    def clean(self):
        super().clean()

        if not self.cleaned_data.get("selected_jobs") and not self.cleaned_data.get("spontaneous_application"):
            raise forms.ValidationError("Sélectionner au moins une option.")
        if self.cleaned_data.get("selected_jobs") and self.cleaned_data.get("spontaneous_application"):
            raise forms.ValidationError(
                f"Vous ne pouvez pas sélectionner des métiers et '{self.fields['spontaneous_application'].label}'."
            )


class SubmitJobApplicationForm(forms.Form):
    """
    Submit a job application to a company.
    """

    resume = ItouFileField(
        label="Curriculum Vitae (CV)",
        required=False,
        content_type="application/pdf",
        max_upload_size=5 * global_constants.MB,
    )

    def __init__(self, company, user, auto_prescription_process, *args, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        self.fields.update(forms.fields_for_model(JobApplication, fields=["message"]))
        message = self.fields["message"]
        message.required = not auto_prescription_process
        message.widget.attrs["placeholder"] = ""
        if user.is_job_seeker:
            message.label = "Message à l’employeur"
            help_text = "Message obligatoire à destination de l’employeur et non modifiable après l’envoi."
        elif auto_prescription_process:
            message.label = "Message d’information"
            help_text = "Ce message ne sera plus modifiable après l’envoi et une copie sera transmise au candidat."
        else:
            message.label = "Message à l’employeur (avec copie transmise au candidat)"
            help_text = "Message obligatoire et non modifiable après l’envoi."
        message.help_text = help_text


class TransferJobApplicationForm(SubmitJobApplicationForm):
    keep_original_resume = forms.NullBooleanField(
        widget=forms.RadioSelect(
            choices=(
                (True, "Oui, conserver le CV de la candidature d’origine."),
                (False, "Non. Ne pas conserver le CV de la candidature d’origine. Je peux joindre un nouveau CV."),
            )
        ),
        required=False,
    )

    def __init__(self, company, user, auto_prescription_process, *args, original_job_application, **kwargs):
        super().__init__(company, user, auto_prescription_process, *args, **kwargs)
        self.original_job_application = original_job_application
        if self.original_job_application.resume_link:
            self.fields["resume"].label = "Joindre un nouveau Curriculum Vitae (CV)"

    def clean_keep_original_resume(self):
        value = self.cleaned_data.get("keep_original_resume")
        if self.original_job_application.resume_link and value is None:
            raise forms.ValidationError("Ce champ est obligatoire.")
        return value

    def clean(self):
        super().clean()
        if self.cleaned_data.get("keep_original_resume") and self.cleaned_data.get("resume"):
            # Don't load the file since we won't keep it
            del self.cleaned_data["resume"]


def _get_orienter_and_prescriber_nb(job_applications):
    orienters = set()
    prescribers = set()
    for job_application in job_applications:
        if job_application.sender_kind == job_applications_enums.SenderKind.PRESCRIBER:
            if job_application.is_sent_by_authorized_prescriber:
                prescribers.add(job_application.sender_id)
            else:
                orienters.add(job_application.sender_id)
    return len(orienters), len(prescribers)


class JobApplicationRefusalReasonForm(forms.Form):
    refusal_reason = forms.ChoiceField(
        widget=forms.RadioSelect,
        choices=job_applications_enums.RefusalReason.displayed_choices(),
    )
    refusal_reason_shared_with_job_seeker = forms.BooleanField(required=False)

    def __init__(self, job_applications, *args, **kwargs):
        super().__init__(*args, **kwargs)
        companies = set(job_application.to_company for job_application in job_applications)
        assert len(companies) == 1, f"Cannot handle batch of applications from different companies: {companies}"
        company = list(companies)[0]

        job_seeker_nb = len(set(job_application.job_seeker_id for job_application in job_applications))
        self.fields[
            "refusal_reason_shared_with_job_seeker"
        ].label = f"J’accepte d’envoyer le motif de refus {pluralizefr(job_seeker_nb, 'au candidat,aux candidats')}"

        orienter_nb, prescriber_nb = _get_orienter_and_prescriber_nb(job_applications)
        if orienter_nb and not prescriber_nb:
            label = f"Choisir le motif de refus envoyé {pluralizefr(orienter_nb, 'à l’orienteur,aux orienteurs')}"
        elif prescriber_nb and not orienter_nb:
            label = (
                f"Choisir le motif de refus envoyé {pluralizefr(prescriber_nb, 'au prescripteur,aux prescripteurs')}"
            )
        elif prescriber_nb and orienter_nb:
            label = "Choisir le motif de refus envoyé aux prescripteurs/orienteurs"
        else:
            label = "Choisir le motif de refus"
        self.fields["refusal_reason"].label = label

        if company.kind == CompanyKind.GEIQ:
            self.fields["refusal_reason"].choices = job_applications_enums.RefusalReason.displayed_choices(
                extra_exclude_enums=[
                    job_applications_enums.RefusalReason.PREVENT_OBJECTIVES,
                    job_applications_enums.RefusalReason.NON_ELIGIBLE,
                ]
            )
        if company.department in settings.JOB_APPLICATION_OPTIONAL_REFUSAL_REASON_DEPARTMENTS:
            self.fields["refusal_reason"].required = False


class JobApplicationRefusalJobSeekerAnswerForm(forms.Form):
    job_seeker_answer = forms.CharField(
        label="Commentaire envoyé au candidat",
        widget=forms.Textarea(),
        strip=True,
    )

    def __init__(self, job_applications, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if len(set(job_application.job_seeker_id for job_application in job_applications)) > 1:
            self.fields["job_seeker_answer"].label = "Commentaire envoyé aux candidats"


class JobApplicationRefusalPrescriberAnswerForm(forms.Form):
    prescriber_answer = forms.CharField(
        widget=forms.Textarea(),
        strip=True,
    )

    def __init__(self, job_applications, *args, **kwargs):
        super().__init__(*args, **kwargs)
        orienter_nb, prescriber_nb = _get_orienter_and_prescriber_nb(job_applications)
        jobseeker_nb = len(set(job_application.job_seeker_id for job_application in job_applications))
        if orienter_nb and not prescriber_nb:
            label = f"Commentaire envoyé {pluralizefr(orienter_nb, 'à l’orienteur,aux orienteurs')}"
        elif prescriber_nb and not orienter_nb:
            label = f"Commentaire envoyé {pluralizefr(prescriber_nb, 'au prescripteur,aux prescripteurs')}"
        else:
            label = "Commentaire envoyé aux orienteurs/prescripteurs"
        label += f" (n’est pas communiqué {pluralizefr(jobseeker_nb, 'au candidat,aux candidats')})"

        self.fields["prescriber_answer"].label = label


class AnswerForm(forms.Form):
    """
    Allow a company to add an answer message when postponing.
    """

    answer = forms.CharField(
        label="Réponse",
        widget=forms.Textarea(attrs={"placeholder": "Votre réponse sera visible par le candidat et le prescripteur"}),
        required=False,
        strip=True,
    )


class AcceptForm(JobAppellationAndLocationMixin, forms.ModelForm):
    """
    Allow a company to accept a job application.
    If company is a GEIQ, add specific fields (contract type, number of hours per week)
    """

    SIAE_OPTIONAL_FIELDS = (
        "hired_job",
        "location",
        "appellation",
    )

    GEIQ_REQUIRED_FIELDS = (
        "prehiring_guidance_days",
        "contract_type",
        "contract_type_details",
        "nb_hours_per_week",
        "qualification_type",
        "qualification_level",
        "planned_training_hours",
        "inverted_vae_contract",
        "hired_job",
    )

    OTHER_HIRED_JOB = "other"

    # Choices are dynamically set on HTMX reload
    qualification_level = forms.ChoiceField(choices=[], label="Niveau de qualification")

    # Can't use a `ModelChoiceField`: choices are constrained (can't add custom value)
    hired_job = forms.ChoiceField(label="Poste retenu")

    class Meta:
        model = JobApplication
        fields = [
            "prehiring_guidance_days",
            "location",
            "contract_type",
            "contract_type_details",
            "nb_hours_per_week",
            "hiring_start_at",
            "qualification_level",
            "qualification_type",
            "planned_training_hours",
            "hiring_end_at",
            "answer",
            "inverted_vae_contract",
        ]
        help_texts = {
            # Make it clear to employers that `hiring_start_at` has an impact on the start of the
            # "parcours IAE" and the payment of the "aide au poste".
            "hiring_start_at": (
                "Au format JJ/MM/AAAA, par exemple {}. Il n'est pas possible d'antidater un contrat.".format(
                    timezone.localdate().strftime("%d/%m/%Y")
                )
            ),
            "hiring_end_at": "Au format JJ/MM/AAAA, par exemple {}.".format(
                (timezone.localdate() + datetime.timedelta(days=Approval.DEFAULT_APPROVAL_DAYS)).strftime("%d/%m/%Y")
            ),
            "prehiring_guidance_days": """Laissez "0" si vous n'avez pas accompagné le candidat avant son embauche""",
            "contract_type_details": (
                "Si vous avez choisi un autre type de contrat, merci de bien vouloir fournir plus de précisions"
            ),
        }

    def __init__(self, *args, company, job_seeker=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.is_geiq = company.kind == CompanyKind.GEIQ
        self.job_seeker = job_seeker
        attrs_min = {}
        attrs_max = {}
        if not self.is_geiq:
            today = timezone.localdate()
            attrs_min["min"] = today.isoformat()
            attrs_max["max"] = (today + relativedelta(months=6)).isoformat()
        self.fields["hiring_start_at"].required = True
        self.fields["hiring_start_at"].widget = DuetDatePickerWidget(attrs=attrs_min | attrs_max)
        self.fields["hiring_end_at"].widget = DuetDatePickerWidget(attrs=attrs_min)
        # Job applications can be accepted twice if they have been cancelled.
        # They also can be accepted after a refusal.
        # That's why some fields are already filled in with obsolete data.
        # Erase them now to start from new.
        for field in ["answer", "hiring_start_at", "hiring_end_at", "contract_type", "contract_type_details"]:
            self.initial[field] = ""
        self.initial["nb_hours_per_week"] = None
        post_data = kwargs.get("data")

        # Remove or make GEIQ specific fields mandatory
        for geiq_field_name in self.GEIQ_REQUIRED_FIELDS:
            if self.is_geiq:
                # Contract type details are dynamic and not required all the time
                self.fields[geiq_field_name].required = geiq_field_name not in (
                    "contract_type_details",
                    "inverted_vae_contract",
                )
            else:
                if geiq_field_name not in self.SIAE_OPTIONAL_FIELDS:
                    self.fields.pop(geiq_field_name)

        if self.is_geiq:
            # Change default size (too large)
            self.fields["contract_type_details"].widget.attrs.update({"rows": 2})
            self.initial["prehiring_guidance_days"] = 0
            self.initial["planned_training_hours"] = 0
            self.fields["hiring_start_at"].help_text = "Au format JJ/MM/AAAA, par exemple {}.".format(
                timezone.localdate().strftime("%d/%m/%Y"),
            )
            # Dynamic selection of qualification level
            post_url = (
                reverse(
                    "apply:reload_qualification_fields",
                    kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
                )
                if job_seeker is not None
                else reverse(
                    "apply:reload_qualification_fields_job_seekerless",
                    kwargs={"company_pk": company.pk},
                )
            )
            self.fields["qualification_type"].widget.attrs.update(
                {
                    "hx-trigger": "change",
                    "hx-post": post_url,
                    "hx-swap": "outerHTML",
                    "hx-select": "#geiq_qualification_fields_block",
                    "hx-target": "#geiq_qualification_fields_block",
                },
            )
            # Set dynamically in a custom form field,
            # otherwise choices values are overriden at every HTMX reload
            self.fields["qualification_level"].choices = (
                BLANK_CHOICE_DASH + job_applications_enums.QualificationLevel.choices
            )
            if (
                post_data
                and post_data.get("qualification_type") == job_applications_enums.QualificationType.STATE_DIPLOMA
            ):
                # Remove irrelevant option
                idx = 1 + job_applications_enums.QualificationLevel.values.index(
                    job_applications_enums.QualificationLevel.NOT_RELEVANT
                )
                self.fields["qualification_level"].choices.pop(idx)
                # Needed to trigger the property.setter
                self.fields["qualification_level"].choices = self.fields["qualification_level"].choices

            self.fields["inverted_vae_contract"].widget = forms.CheckboxInput()
            self.fields["inverted_vae_contract"].disabled = not (
                post_data and post_data.get("contract_type") == ContractType.PROFESSIONAL_TRAINING
            )
            post_url = (
                reverse(
                    "apply:reload_contract_type_and_options",
                    kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
                )
                if job_seeker is not None
                else reverse(
                    "apply:reload_contract_type_and_options_job_seekerless",
                    kwargs={"company_pk": company.pk},
                )
            )
            self.fields["contract_type"].widget.attrs.update(
                {
                    "hx-trigger": "change",
                    "hx-post": post_url,
                    "hx-swap": "outerHTML",
                    "hx-select": "#geiq_contract_type_and_options_block",
                    "hx-target": "#geiq_contract_type_and_options_block",
                },
            )
        elif company.kind in CompanyKind.siae_kinds():
            # Add specific details to help texts for IAE
            self.fields["hiring_start_at"].help_text += (
                " La date est modifiable jusqu'à la veille de la date saisie. En cas de premier PASS IAE pour "
                "la personne, cette date déclenche le début de son parcours."
            )
            self.fields["hiring_end_at"].help_text += (
                " Elle sert uniquement à des fins d'informations et est sans conséquence sur les déclarations "
                "à faire dans l'extranet 2.0 de l'ASP. "
                "<b>Ne pas compléter cette date dans le cadre d’un CDI Inclusion</b>"
            )

        # `hired_job` can't be used from model directly because of constrained choices
        # we must use a "simple" ChoiceField and update the value on cleaning
        self.fields["hired_job"].required = self.is_geiq

        def sorted_jobs_for_display(jobs):
            return sorted(
                [
                    (job_description.pk, f"{job_description.display_name} - {job_description.display_location}")
                    for job_description in jobs
                ],
                key=itemgetter(1),
            )

        choices = [("", "Sélectionnez un poste")]
        if (
            jobs := company.job_description_through.all()
            .select_related("appellation", "location")
            .order_by("custom_name", "is_active")
        ):
            if active_jobs := sorted_jobs_for_display(job for job in jobs if job.is_active):
                choices.append(("Postes ouverts au recrutement", active_jobs))
            if inactive_jobs := sorted_jobs_for_display(job for job in jobs if not job.is_active):
                choices.append(("Postes fermés au recrutement", inactive_jobs))
        choices.append(
            (
                "Métiers non présents dans ma structure",
                [(self.OTHER_HIRED_JOB, "Ajouter un poste lié à un nouveau métier")],
            )
        )
        self.fields["hired_job"].choices = choices
        post_url = (
            reverse(
                "apply:reload_job_description_fields",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
            if job_seeker is not None
            else reverse(
                "apply:reload_job_description_fields_job_seekerless",
                kwargs={"company_pk": company.pk},
            )
        )
        self.fields["hired_job"].widget.attrs.update(
            {
                "hx-post": post_url,
                "hx-swap": "outerHTML",
                "hx-select": "#job_description_fields_block",
                "hx-target": "#job_description_fields_block",
            }
        )

        self.fields["appellation"].label = "Préciser le nom du poste (code ROME)"
        self.fields["location"].label = "Localisation du poste"

    def clean_hiring_start_at(self):
        hiring_start_at = self.cleaned_data["hiring_start_at"]

        # Hiring in the past is *temporarily* possible for GEIQ
        if hiring_start_at and hiring_start_at < timezone.localdate() and not self.is_geiq:
            self.add_error("hiring_start_at", forms.ValidationError(JobApplication.ERROR_START_IN_PAST))
        elif hiring_start_at and hiring_start_at > timezone.localdate() + relativedelta(months=6):
            self.add_error("hiring_start_at", forms.ValidationError(JobApplication.ERROR_START_IN_FAR_FUTURE))
        else:
            return hiring_start_at

    def clean(self):
        hiring_start_at = self.cleaned_data.get("hiring_start_at")
        hiring_end_at = self.cleaned_data.get("hiring_end_at")

        if hiring_end_at and hiring_start_at and hiring_end_at < hiring_start_at:
            raise forms.ValidationError(JobApplication.ERROR_END_IS_BEFORE_START)

        if self.is_geiq:
            # This validation is enforced by database constraints,
            # but we are nice enough to display a warning message to the user
            # (constraints violation message are generic)
            contract_type = self.cleaned_data.get("contract_type")
            contract_type_details = self.cleaned_data.get("contract_type_details")

            if contract_type == ContractType.OTHER and not contract_type_details:
                self.add_error("contract_type_details", "Les précisions sont nécessaires pour ce type de contrat")

            if contract_type == ContractType.PROFESSIONAL_TRAINING:
                self.cleaned_data["inverted_vae_contract"] = bool(self.cleaned_data.get("inverted_vae_contract"))

        location = self.cleaned_data.get("location")
        appellation = self.cleaned_data.get("appellation")

        if self.cleaned_data.get("hired_job") == self.OTHER_HIRED_JOB:
            if not appellation:
                self.add_error("appellation", forms.ValidationError("Un poste doit être saisi en cas de création"))
            elif not location:
                # location becomes mandatory in this case only:
                self.add_error(
                    "location",
                    forms.ValidationError("La localisation du poste est obligatoire en cas de création"),
                )

    def save(self, commit):
        # We might create a JobDescription here even with atomic==False
        # so we need to wrap the call to save in a atomic transaction
        instance = super().save(commit)
        location = self.cleaned_data.get("location")
        appellation = self.cleaned_data.get("appellation")

        if self.cleaned_data.get("hired_job") == self.OTHER_HIRED_JOB:
            # Check that the new job application is not a duplicate from the list
            if existing_job_description := JobDescription.objects.filter(
                company=self.company, location=location, appellation=appellation
            ).first():
                # Found one matching: reuse it and don't create a new one
                self.instance.hired_job = existing_job_description
            else:
                # If no job description in the list is matching, eventually create a new one:
                # - inactive
                # - marked as autogenerated
                # - associated to current job application
                new_job_description = JobDescription(
                    company=self.company,
                    appellation=appellation,
                    location=location,
                    is_active=False,
                    description="La structure n’a pas encore renseigné cette rubrique",
                    creation_source=JobDescriptionSource.HIRING,
                )
                new_job_description.save()
                instance.hired_job = new_job_description
        else:
            # A job description has been selected is the list: link it to current hiring
            instance.hired_job_id = self.cleaned_data.get("hired_job")
        return instance


class PriorActionForm(forms.ModelForm):
    """
    Allows to add a new prior action or edit one
    """

    class Meta:
        model = PriorAction
        fields = [
            "action",
        ]

    def __init__(self, *args, action_only=False, **kwargs):
        super().__init__(*args, **kwargs)

        # Change empty label from "---------" to our value
        self.fields["action"].choices = [
            (k, v if k else "Ajouter une action") for k, v in self.fields["action"].choices
        ]
        self.action_only = action_only
        if not self.action_only:
            self.fields["start_at"] = forms.DateField(
                label="Date de début",
                widget=DuetDatePickerWidget(),
            )
            self.fields["end_at"] = forms.DateField(
                label="Date de fin prévisionnelle",
                widget=DuetDatePickerWidget(),
            )
            if self.instance.pk:
                self.initial["start_at"] = self.instance.dates.lower
                self.initial["end_at"] = self.instance.dates.upper

    def clean(self):
        super().clean()
        if not self.action_only:
            start_at = self.cleaned_data.get("start_at")
            end_at = self.cleaned_data.get("end_at")

            if end_at and end_at < start_at:
                raise forms.ValidationError("La date de fin prévisionnelle doit être postérieure à la date de début.")

    def save(self, commit=True):
        if self.cleaned_data.get("start_at") and self.cleaned_data.get("end_at"):
            self.instance.dates = InclusiveDateRange(self.cleaned_data["start_at"], self.cleaned_data["end_at"])
        return super().save()


class EditHiringDateForm(forms.ModelForm):
    """
    Allows a company to change contract date (if current one is in the future)
    """

    class Meta:
        model = JobApplication
        fields = ["hiring_start_at", "hiring_end_at"]
        help_texts = {
            "hiring_start_at": (
                "Il n'est pas possible d'antidater un contrat. "
                "Indiquez une date dans le futur. "
                "Cette date peut-être repoussée de 30 jours au plus, "
                "et avant la fin du PASS IAE éventuellement émis pour cette candidature."
            ),
            "hiring_end_at": (
                "Cette date sert uniquement à des fins d'informations et est sans conséquence"
                " sur les déclarations à faire dans l'extranet 2.0 de l'ASP. "
                "<b>Ne pas compléter cette date dans le cadre d’un CDI Inclusion</b>"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hiring_start_at"].required = True
        for field in ["hiring_start_at", "hiring_end_at"]:
            self.fields[field].widget = DuetDatePickerWidget()

    def clean_hiring_start_at(self):
        hiring_start_at = self.cleaned_data["hiring_start_at"]

        if hiring_start_at < timezone.localdate():
            raise forms.ValidationError(JobApplication.ERROR_START_IN_PAST)

        if hiring_start_at > timezone.localdate() + relativedelta(days=JobApplication.MAX_CONTRACT_POSTPONE_IN_DAYS):
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


class JobSeekerPersonalDataForm(JobSeekerNIRUpdateMixin, JobSeekerProfileModelForm):
    """
    Info that will be used to search for an existing Pôle emploi approval.
    """

    PROFILE_FIELDS = JobSeekerProfileModelForm.PROFILE_FIELDS + [
        "pole_emploi_id",
        "lack_of_pole_emploi_id_reason",
        "nir",
        "lack_of_nir_reason",
    ]

    class Meta(JobSeekerProfileModelForm.Meta):
        fields = []

    def clean(self):
        super().clean()
        JobSeekerProfile.clean_pole_emploi_fields(self.cleaned_data)


class FilterJobApplicationsForm(forms.Form):
    """
    Allow users to filter job applications based on specific fields.
    """

    states = forms.MultipleChoiceField(
        required=False,
        choices=job_applications_enums.JobApplicationState,
        widget=forms.CheckboxSelectMultiple,
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

    def filter(self, queryset):
        filters = []
        data = self.cleaned_data

        if states := data.get("states"):
            filters.append(Q(state__in=states))

        if data.get("pass_iae_active") or data.get("pass_iae_suspended"):
            queryset = queryset.with_has_suspended_approval()
            pass_status_filter = Q()
            if data.get("pass_iae_active"):
                # Simplification of CommonApprovalQuerySet.valid_lookup()
                # The date is not enough to know if an approval is valid or not
                pass_status_filter |= Q(approval__end_at__gte=timezone.localdate(), has_suspended_approval=False)

            if data.get("pass_iae_suspended"):
                # This is NOT what we want but how things work currently:
                # if you check pass_iae_active, the value of pass_iae_suspended is ignored
                # Filter on the `has_suspended_approval` annotation, which is set in `with_list_related_data()`.
                pass_status_filter |= Q(has_suspended_approval=True)
            filters.append(pass_status_filter)

        if start_date := data.get("start_date"):
            filters.append(Q(created_at__gte=start_date))
        if end_date := data.get("end_date"):
            filters.append(Q(created_at__lte=end_date))
        if departments := data.get("departments"):
            filters.append(Q(job_seeker__department__in=departments))
        if selected_jobs := data.get("selected_jobs"):
            filters.append(Q(selected_jobs__appellation__code__in=selected_jobs))
        if criteria := data.get("criteria"):
            # Filter on the `eligibility_diagnosis_criterion_{criterion}` annotation,
            # which is set in `with_list_related_data()`.
            for criterion in criteria:
                filters.append(Q(**{f"eligibility_diagnosis_criterion_{criterion}": True}))

        return queryset.filter(*filters)

    def get_qs_filters_counter(self):
        """
        Get number of filters selected.
        """
        return sum(bool(self.cleaned_data.get(field.name)) for field in self)


class ArchivedChoices(TextChoices):
    ACTIVE = "", "Candidatures actives (affichage par défaut)"
    ARCHIVED = "archived", "Candidatures archivées"
    ALL = "all", "Toutes les candidatures"


class CompanyPrescriberFilterJobApplicationsForm(FilterJobApplicationsForm):
    """
    Job applications filters common to companies and Prescribers.
    """

    senders = forms.MultipleChoiceField(required=False, label="Nom de la personne", widget=Select2MultipleWidget)
    job_seeker = forms.ChoiceField(
        required=False,
        label="Nom du candidat",
        widget=Select2Widget(
            attrs={"data-placeholder": "Nom du candidat"},
        ),
    )

    pass_iae_suspended = forms.BooleanField(label="Suspendu", required=False)
    pass_iae_active = forms.BooleanField(label="Actif", required=False)
    criteria = forms.MultipleChoiceField(required=False, label="", widget=Select2MultipleWidget)
    eligibility_validated = forms.BooleanField(label="Éligibilité validée", required=False)
    departments = forms.MultipleChoiceField(
        required=False,
        label="Départements",
        widget=forms.CheckboxSelectMultiple(),
    )
    selected_jobs = forms.MultipleChoiceField(
        required=False,
        label="Fiches de poste",
        widget=forms.CheckboxSelectMultiple(),
    )
    archived = forms.ChoiceField(
        choices=ArchivedChoices,
        widget=forms.RadioSelect,
        label="",  # Labeled by the fieldset.
        required=False,
    )

    @sentry_sdk.trace
    def __init__(self, job_applications_qs, *args, **kwargs):
        self.job_applications_qs = job_applications_qs
        super().__init__(*args, **kwargs)
        senders = self.job_applications_qs.get_unique_fk_objects("sender")
        self.fields["senders"].choices += self._get_choices_for_sender(senders)
        job_seekers = self.job_applications_qs.get_unique_fk_objects("job_seeker")
        self.fields["job_seeker"].choices = self._get_choices_for_job_seeker(job_seekers)
        self.fields["criteria"].choices = self._get_choices_for_administrativecriteria()
        self.fields["departments"].choices = self._get_choices_for_departments(job_seekers)
        self.fields["selected_jobs"].choices = self._get_choices_for_jobs()

    def _get_choices_for_sender(self, users):
        users = [(user.id, user_full_name) for user in users if (user_full_name := user.get_full_name())]
        return sorted(users, key=lambda user: user[1])

    def _get_choices_for_administrativecriteria(self):
        return [(c.pk, c.name) for c in AdministrativeCriteria.objects.all()]

    def _get_choices_for_departments(self, job_seekers):
        departments = {
            (user.department, DEPARTMENTS.get(user.department))
            for user in job_seekers
            if user.department in DEPARTMENTS
        }
        return sorted(departments, key=lambda dpts: dpts[1])

    def _get_choices_for_jobs(self):
        jobs = set()
        for job_application in self.job_applications_qs.prefetch_related("selected_jobs__appellation"):
            for job in job_application.selected_jobs.all():
                jobs.add((job.appellation.code, job.appellation.name))
        return sorted(jobs, key=lambda job: job[1])

    def filter(self, queryset):
        queryset = super().filter(queryset)
        if self.cleaned_data.get("eligibility_validated"):
            queryset = queryset.eligibility_validated()

        if senders := self.cleaned_data.get("senders"):
            queryset = queryset.filter(sender__id__in=senders)

        if job_seeker := self.cleaned_data.get("job_seeker"):
            queryset = queryset.filter(job_seeker__id=job_seeker)

        archived = self.cleaned_data["archived"]
        if archived == ArchivedChoices.ACTIVE:
            queryset = queryset.filter(archived_at=None)
        elif archived == ArchivedChoices.ARCHIVED:
            queryset = queryset.exclude(archived_at=None)

        return queryset


class CompanyFilterJobApplicationsForm(CompanyPrescriberFilterJobApplicationsForm):
    """
    Job applications filters for companies only.
    """

    sender_prescriber_organizations = forms.MultipleChoiceField(
        required=False,
        label="Nom de l'organisme prescripteur",
        widget=Select2MultipleWidget,
    )

    sender_companies = forms.MultipleChoiceField(
        required=False,
        label="Nom de l’employeur orienteur",
        widget=Select2MultipleWidget,
    )

    def __init__(self, job_applications_qs, company, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["sender_prescriber_organizations"].choices += self.get_sender_prescriber_organization_choices()
        self.fields["sender_companies"].choices += self.get_sender_companies_choices()

        if company.kind not in CompanyKind.siae_kinds():
            del self.fields["eligibility_validated"]
            del self.fields["pass_iae_active"]
            del self.fields["pass_iae_suspended"]

        if not company.can_have_prior_action:
            # Drop "pré-embauche" state from filter for non-GEIQ companies
            self.fields["states"].choices = [
                (k, v)
                for k, v in self.fields["states"].choices
                if k != job_applications_enums.JobApplicationState.PRIOR_TO_HIRE
            ]

    def filter(self, queryset):
        queryset = super().filter(queryset)
        if sender_prescriber_organizations := self.cleaned_data.get("sender_prescriber_organizations"):
            queryset = queryset.filter(sender_prescriber_organization__id__in=sender_prescriber_organizations)
        if sender_companies := self.cleaned_data.get("sender_companies"):
            queryset = queryset.filter(sender_company__id__in=sender_companies)
        return queryset

    def _get_choices_for_job_seeker(self, users):
        users = [(user.id, user_full_name) for user in users if (user_full_name := user.get_full_name())]
        return sorted(users, key=lambda user: user[1])

    def get_sender_prescriber_organization_choices(self):
        sender_orgs = self.job_applications_qs.get_unique_fk_objects("sender_prescriber_organization")
        sender_orgs = [sender for sender in sender_orgs if sender.display_name]
        sender_orgs = [(sender.id, sender.display_name.title()) for sender in sender_orgs]
        return sorted(sender_orgs, key=lambda org: org[0])

    def get_sender_companies_choices(self):
        sender_orgs = self.job_applications_qs.get_unique_fk_objects("sender_company")
        sender_orgs = [sender for sender in sender_orgs if sender.display_name]
        sender_orgs = [(sender.id, sender.display_name.title()) for sender in sender_orgs]
        return sorted(sender_orgs, key=lambda org: org[0])


class PrescriberFilterJobApplicationsForm(CompanyPrescriberFilterJobApplicationsForm):
    """
    Job applications filters for Prescribers only.
    """

    to_companies = forms.MultipleChoiceField(required=False, label="Organisation", widget=Select2MultipleWidget)

    def __init__(self, job_applications_qs, *args, request_user, **kwargs):
        self.request_user = request_user
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["to_companies"].choices += self.get_to_companies_choices()

    def _get_choices_for_job_seeker(self, users):
        users = [
            (
                user.id,
                mask_unless(user_full_name, predicate=self.request_user.can_view_personal_information(user)),
            )
            for user in users
            if (user_full_name := user.get_full_name())
        ]
        return sorted(users, key=lambda user: user[1])

    def filter(self, queryset):
        queryset = super().filter(queryset)
        if to_companies := self.cleaned_data.get("to_companies"):
            queryset = queryset.filter(to_company__id__in=to_companies)
        return queryset

    def get_to_companies_choices(self):
        to_companies = self.job_applications_qs.get_unique_fk_objects("to_company")
        to_companies = [company for company in to_companies if company.display_name]
        to_companies = [(company.id, company.display_name.title()) for company in to_companies]
        return sorted(to_companies, key=lambda company: company[1])


class CheckJobSeekerGEIQEligibilityForm(forms.Form):
    choice = forms.BooleanField(required=False, widget=forms.RadioSelect(choices=((True, "Oui"), (False, "Non"))))

    def __init__(self, hx_post_url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["choice"].widget.attrs.update({"hx-trigger": "change", "hx-post": hx_post_url})


class BatchPostponeForm(AnswerForm):
    def __init__(self, *args, job_seeker_nb, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["answer"].widget.attrs["placeholder"] = (
            "Votre réponse sera visible par les candidats et les prescripteurs/orienteurs"
        )
        if job_seeker_nb is not None:
            self.fields["answer"].label = (
                f"Commentaire à envoyer aux {job_seeker_nb} candidats"
                if job_seeker_nb > 1
                else "Commentaire à envoyer au candidat"
            )
