import contextlib
import datetime
from operator import itemgetter

import sentry_sdk
from dateutil.relativedelta import relativedelta
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db.models import Q
from django.db.models.fields import BLANK_CHOICE_DASH
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django_select2.forms import Select2MultipleWidget

from itou.approvals.models import Approval
from itou.asp import models as asp_models
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, department_from_postcode
from itou.common_apps.address.forms import MandatoryAddressFormMixin
from itou.common_apps.nir.forms import JobSeekerNIRUpdateMixin
from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS, CompanyKind, ContractType, JobDescriptionSource
from itou.companies.models import JobDescription
from itou.eligibility.models import AdministrativeCriteria
from itou.files.forms import ItouFileField
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationWorkflow, PriorAction
from itou.users.enums import LackOfPoleEmploiId, UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.emails import redact_email_address
from itou.utils.types import InclusiveDateRange
from itou.utils.validators import validate_nir, validate_pole_emploi_id
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.companies_views.forms import JobAppellationAndLocationMixin


class JobSeekerExistsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None

    email = forms.EmailField(
        label="Adresse e-mail du candidat",
        widget=forms.EmailInput(attrs={"autocomplete": "off", "placeholder": "julie@example.com"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if email.endswith(global_constants.POLE_EMPLOI_EMAIL_SUFFIX):
            raise ValidationError("Vous ne pouvez pas utiliser un e-mail Pôle emploi pour un candidat.")
        if email.endswith(global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX):
            raise ValidationError("Vous ne pouvez pas utiliser un e-mail France Travail pour un candidat.")
        self.user = User.objects.filter(email__iexact=email).first()
        if self.user:
            if not self.user.is_active:
                error = "Vous ne pouvez pas postuler pour cet utilisateur car son compte a été désactivé."
                raise forms.ValidationError(error)
            if not self.user.is_job_seeker:
                error = (
                    "Vous ne pouvez pas postuler pour cet utilisateur car"
                    "cet e-mail est déjà rattaché à un prescripteur ou à un employeur."
                )
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
                    "Ce numéro de sécurité sociale est déjà utilisé par un autre compte. Merci de vous "
                    "reconnecter avec l'adresse e-mail <b>{}</b>. "
                    "Si vous ne vous souvenez plus de votre mot de passe, vous pourrez "
                    "cliquer sur « mot de passe oublié ». "
                    'En cas de souci, vous pouvez <a href="{}" rel="noopener" '
                    'target="_blank" aria-label="Ouverture dans un nouvel onglet">nous contacter</a>.'
                )
                raise forms.ValidationError(
                    format_html(
                        error_message,
                        redact_email_address(existing_account.email),
                        global_constants.ITOU_HELP_CENTER_URL,
                    )
                )
        else:
            # For the moment, consider NIR to be unique among users.
            self.job_seeker = existing_account
        return nir

    def clean(self):
        super().clean()
        if self.job_seeker and self.job_seeker.kind != UserKind.JOB_SEEKER:
            error_message = (
                "Vous ne pouvez postuler pour cet utilisateur car ce numéro de sécurité sociale "
                "n'est pas associé à un compte candidat."
            )
            raise forms.ValidationError(error_message)

    def get_job_seeker(self):
        return self.job_seeker


class CheckJobSeekerInfoForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "birthdate",
            "phone",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
        ]
        help_texts = {
            "birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].required = True
        self.fields["birthdate"].widget = DuetDatePickerWidget(
            {
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )

    def clean(self):
        super().clean()
        self._meta.model.clean_pole_emploi_fields(self.cleaned_data)


class CreateOrUpdateJobSeekerStep1Form(JobSeekerNIRUpdateMixin, forms.ModelForm):
    REQUIRED_FIELDS = [
        "title",
        "first_name",
        "last_name",
        "birthdate",
    ]

    class Meta:
        model = User
        fields = [
            "nir",
            "lack_of_nir_reason",
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


class CreateOrUpdateJobSeekerStep2Form(MandatoryAddressFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "address_line_1",
            "address_line_2",
            "post_code",
            "city_slug",
            "city",
            "phone",
        ]

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

        if post_code := self.cleaned_data.get("post_code"):
            self.cleaned_data["department"] = department_from_postcode(post_code)


class CreateOrUpdateJobSeekerStep3Form(forms.ModelForm):
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
        required=False,
        label="Majoration du RSA",
        choices=asp_models.RSAAllocation.choices[1:],
    )

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["education_level"].required = True
        self.fields["education_level"].label = "Niveau de formation"

        if self.instance:
            # if an instance is provided, make sure the initial values for non-model fields are consistent
            for field in [
                "pole_emploi",
                "unemployed",
                "rsa_allocation",
                "ass_allocation",
                "aah_allocation",
            ]:
                if field not in self.initial:
                    self.initial[field] = bool(getattr(self.instance, f"{field}_since"))

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
                self.cleaned_data["lack_of_pole_emploi_id_reason"] = LackOfPoleEmploiId.REASON_FORGOTTEN
                self.cleaned_data["pole_emploi_id"] = ""
            elif self.cleaned_data.get("pole_emploi_id"):
                self.cleaned_data["lack_of_pole_emploi_id_reason"] = ""
            elif not self.cleaned_data.get("pole_emploi_id") and not self.has_error("pole_emploi_id"):
                # The 'pole_emploi_id' field is missing when its validation fails,
                # also don't stack a 'missing field' error if an error already exists ('wrong format' in this case)
                self.add_error(
                    "pole_emploi_id",
                    forms.ValidationError("L'identifiant Pôle emploi est obligatoire"),
                )
        else:
            self.cleaned_data["pole_emploi_id_forgotten"] = ""
            self.cleaned_data["pole_emploi_id"] = ""
            self.cleaned_data["lack_of_pole_emploi_id_reason"] = LackOfPoleEmploiId.REASON_NOT_REGISTERED

        # Handle RSA extra fields
        if self.cleaned_data["rsa_allocation"]:
            if not self.cleaned_data["has_rsa_allocation"]:
                self.add_error(
                    "has_rsa_allocation",
                    forms.ValidationError("La majoration RSA est obligatoire"),
                )
        else:
            self.cleaned_data["has_rsa_allocation"] = asp_models.RSAAllocation.NO


class ApplicationJobsForm(forms.ModelForm):
    spontaneous_application = forms.BooleanField(
        required=False,
        label="Candidature spontanée",
    )

    class Meta:
        model = JobApplication
        fields = ["selected_jobs", "spontaneous_application"]
        widgets = {
            "selected_jobs": forms.CheckboxSelectMultiple,
        }

    def __init__(self, company, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["selected_jobs"].queryset = (
            company.job_description_through.active().with_annotation_is_popular().prefetch_related("appellation")
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

    def __init__(self, company, user, *args, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        self.fields.update(forms.fields_for_model(JobApplication, fields=["selected_jobs", "message"]))
        selected_jobs = self.fields["selected_jobs"]
        selected_jobs.queryset = company.job_description_through.filter(is_active=True)
        selected_jobs.widgets = forms.CheckboxSelectMultiple()
        selected_jobs.label = "Métiers recherchés"

        message = self.fields["message"]
        message.required = not user.is_employer
        message.widget.attrs["placeholder"] = ""
        if user.is_job_seeker:
            message.label = "Message à l’employeur"
            help_text = "Message obligatoire à destination de l’employeur et non modifiable après l’envoi."
        elif user.is_employer:
            message.label = "Message d’information"
            help_text = "Ce message ne sera plus modifiable après l’envoi et une copie sera transmise au candidat."
        else:
            message.label = "Message à l’employeur (avec copie transmise au candidat)"
            help_text = "Message obligatoire et non modifiable après l’envoi."
        message.help_text = help_text


class RefusalForm(forms.Form):
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
        if job_application.to_company.kind == CompanyKind.GEIQ:
            self.fields["refusal_reason"].choices = job_applications_enums.RefusalReason.displayed_choices(
                extra_exclude_enums=[
                    job_applications_enums.RefusalReason.PREVENT_OBJECTIVES,
                    job_applications_enums.RefusalReason.NON_ELIGIBLE,
                ]
            )

        if job_application.sender_kind != job_applications_enums.SenderKind.PRESCRIBER:
            self.fields.pop("answer_to_prescriber")
            self.fields["answer"].label = "Message à envoyer au candidat"


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
                    datetime.date.today().strftime("%d/%m/%Y")
                )
            ),
            "hiring_end_at": "Au format JJ/MM/AAAA, par exemple {}.".format(
                (datetime.date.today() + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)).strftime("%d/%m/%Y")
            ),
            "prehiring_guidance_days": """Laissez "0" si vous n'avez pas accompagné le candidat avant son embauche""",
            "contract_type_details": (
                "Si vous avez choisi un autre type de contrat, merci de bien vouloir fournir plus de précisions"
            ),
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.is_geiq = company.kind == CompanyKind.GEIQ

        self.fields["hiring_start_at"].required = True
        for field in ["hiring_start_at", "hiring_end_at"]:
            self.fields[field].widget = DuetDatePickerWidget()
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
                datetime.date.today().strftime("%d/%m/%Y"),
            )
            # Dynamic selection of qualification level
            self.fields["qualification_type"].widget.attrs.update(
                {
                    "hx-trigger": "change",
                    "hx-post": reverse("apply:reload_qualification_fields", kwargs={"company_pk": company.pk}),
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

            self.fields["inverted_vae_contract"].widget = forms.CheckboxInput()
            self.fields["inverted_vae_contract"].disabled = not (
                post_data and post_data.get("contract_type") == ContractType.PROFESSIONAL_TRAINING
            )
            self.fields["contract_type"].widget.attrs.update(
                {
                    "hx-trigger": "change",
                    "hx-post": reverse("apply:reload_contract_type_and_options", kwargs={"company_pk": company.pk}),
                    "hx-swap": "outerHTML",
                    "hx-select": "#geiq_contract_type_and_options_block",
                    "hx-target": "#geiq_contract_type_and_options_block",
                },
            )
        elif company.kind in SIAE_WITH_CONVENTION_KINDS:
            # Add specific details to help texts for IAE
            self.fields["hiring_start_at"].help_text += (
                " La date est modifiable jusqu'à la veille de la date saisie. En cas de premier PASS IAE pour "
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
        if jobs := company.job_description_through.all().order_by("custom_name", "is_active"):
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
        self.fields["hired_job"].widget.attrs.update(
            {
                "hx-post": reverse("apply:reload_job_description_fields", kwargs={"company_pk": company.pk}),
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
        if hiring_start_at and hiring_start_at < datetime.date.today() and not self.is_geiq:
            self.add_error("hiring_start_at", forms.ValidationError(JobApplication.ERROR_START_IN_PAST))
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
                "et avant la fin du PASS IAE éventuellement émis pour cette candidature."
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


class JobSeekerPersonalDataForm(JobSeekerNIRUpdateMixin, forms.ModelForm):
    """
    Info that will be used to search for an existing Pôle emploi approval.
    """

    class Meta:
        model = User
        fields = ["nir", "lack_of_nir_reason", "birthdate", "pole_emploi_id", "lack_of_pole_emploi_id_reason"]
        help_texts = {"birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["birthdate"].widget = DuetDatePickerWidget(
            attrs={
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )

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
        required=False,
        choices=JobApplicationWorkflow.STATE_CHOICES,
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

    def get_qs_filters(self):
        """
        Get filters to be applied to a query set.
        """
        filters = []
        data = self.cleaned_data

        if states := data.get("states"):
            filters.append(Q(state__in=states))

        if data.get("pass_iae_active"):
            filters.append(
                # Simplification of CommonApprovalQuerySet.valid_lookup()
                # The date is not enough to know if an approval is valid or not
                Q(approval__end_at__gte=timezone.localdate(), has_suspended_approval=False)
            )
        elif data.get("pass_iae_suspended"):
            # This is NOT what we want but how things work currently:
            # if you check pass_iae_active, the value of pass_iae_suspended is ignored
            # Filter on the `has_suspended_approval` annotation, which is set in `with_list_related_data()`.
            filters.append(Q(has_suspended_approval=True))

        if data.get("eligibility_validated"):
            filters.append(Q(jobseeker_eligibility_diagnosis__isnull=False))
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

        return filters

    def get_qs_filters_counter(self):
        """
        Get number of filters selected.
        """
        return sum(bool(self.cleaned_data.get(field.name)) for field in self)


class CompanyPrescriberFilterJobApplicationsForm(FilterJobApplicationsForm):
    """
    Job applications filters common to companies and Prescribers.
    """

    senders = forms.MultipleChoiceField(required=False, label="Nom de la personne", widget=Select2MultipleWidget)
    job_seekers = forms.MultipleChoiceField(required=False, label="Nom du candidat", widget=Select2MultipleWidget)

    pass_iae_suspended = forms.BooleanField(label="Suspendu", required=False)
    pass_iae_active = forms.BooleanField(label="Actif", required=False)
    criteria = forms.MultipleChoiceField(required=False, label="", widget=Select2MultipleWidget)
    eligibility_validated = forms.BooleanField(label="Éligibilité validée", required=False)
    departments = forms.MultipleChoiceField(
        required=False,
        label="Département du candidat",
        widget=forms.CheckboxSelectMultiple,
    )
    selected_jobs = forms.MultipleChoiceField(
        required=False, label="Fiches de poste", widget=forms.CheckboxSelectMultiple
    )

    @sentry_sdk.trace
    def __init__(self, job_applications_qs, *args, **kwargs):
        self.job_applications_qs = job_applications_qs
        super().__init__(*args, **kwargs)
        senders = self.job_applications_qs.get_unique_fk_objects("sender")
        self.fields["senders"].choices += self._get_choices_for(senders)
        job_seekers = self.job_applications_qs.get_unique_fk_objects("job_seeker")
        self.fields["job_seekers"].choices = self._get_choices_for(job_seekers)
        self.fields["criteria"].choices = self._get_choices_for_administrativecriteria()
        self.fields["departments"].choices = self._get_choices_for_departments(job_seekers)
        self.fields["selected_jobs"].choices = self._get_choices_for_jobs()

    def _get_choices_for(self, users):
        users = [user for user in users if user.get_full_name()]
        users = [(user.id, user.get_full_name().title()) for user in users]
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

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        if senders := self.cleaned_data.get("senders"):
            qs_list.append(Q(sender__id__in=senders))

        if job_seekers := self.cleaned_data.get("job_seekers"):
            qs_list.append(Q(job_seeker__id__in=job_seekers))
        return qs_list


class CompanyFilterJobApplicationsForm(CompanyPrescriberFilterJobApplicationsForm):
    """
    Job applications filters for companies only.
    """

    sender_organizations = forms.MultipleChoiceField(
        required=False,
        label="Nom de l'organisme prescripteur",
        widget=Select2MultipleWidget,
    )

    def __init__(self, job_applications_qs, company, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["sender_organizations"].choices += self.get_sender_organization_choices()

        if company.kind not in SIAE_WITH_CONVENTION_KINDS:
            del self.fields["eligibility_validated"]

        if not company.can_have_prior_action:
            # Drop "pré-embauche" state from filter for non-GEIQ companies
            self.fields["states"].choices = [
                (k, v) for k, v in self.fields["states"].choices if k != JobApplicationWorkflow.STATE_PRIOR_TO_HIRE
            ]

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        if sender_organizations := self.cleaned_data.get("sender_organizations"):
            qs_list.append(Q(sender_prescriber_organization__id__in=sender_organizations))
        return qs_list

    def get_sender_organization_choices(self):
        sender_orgs = self.job_applications_qs.get_unique_fk_objects("sender_prescriber_organization")
        sender_orgs = [sender for sender in sender_orgs if sender.display_name]
        sender_orgs = [(sender.id, sender.display_name.title()) for sender in sender_orgs]
        return sorted(sender_orgs, key=lambda org: org[0])


class PrescriberFilterJobApplicationsForm(CompanyPrescriberFilterJobApplicationsForm):
    """
    Job applications filters for Prescribers only.
    """

    to_companies = forms.MultipleChoiceField(required=False, label="Structure", widget=Select2MultipleWidget)

    def __init__(self, job_applications_qs, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["to_companies"].choices += self.get_to_companies_choices()

    def get_qs_filters(self):
        qs_list = super().get_qs_filters()
        if to_companies := self.cleaned_data.get("to_companies"):
            qs_list.append(Q(to_company__id__in=to_companies))
        return qs_list

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
