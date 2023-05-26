import contextlib
import datetime

import sentry_sdk
from dateutil.relativedelta import relativedelta
from django import forms
from django.core.validators import MinLengthValidator
from django.db.models import Q
from django.db.models.fields import BLANK_CHOICE_DASH
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django_select2.forms import Select2MultipleWidget

from itou.approvals.models import Approval
from itou.asp import models as asp_models
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, department_from_postcode
from itou.common_apps.address.forms import MandatoryAddressFormMixin
from itou.common_apps.nir.forms import JobSeekerNIRUpdateMixin
from itou.common_apps.resume.forms import ResumeFormMixin
from itou.eligibility.models import AdministrativeCriteria
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationWorkflow, PriorAction
from itou.siaes.enums import SIAE_WITH_CONVENTION_KINDS, ContractType, SiaeKind
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.types import InclusiveDateRange
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
                    "Ce numéro de sécurité sociale est déjà utilisé par un autre compte. "
                    f"Merci de vous reconnecter avec l'adresse e-mail <b>{existing_account.email}</b>. "
                    "Si vous ne vous souvenez plus de votre mot de passe, vous pourrez "
                    "cliquer sur « mot de passe oublié ». "
                    f'En cas de souci, vous pouvez <a href="{global_constants.ITOU_ASSISTANCE_URL}" rel="noopener" '
                    'target="_blank" aria-label="Ouverture dans un nouvel onglet">nous contacter</a>.'
                )
                raise forms.ValidationError(mark_safe(error_message))
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
        fields = [
            "birthdate",
            "phone",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
        ]
        help_texts = {
            "birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978.",
        }

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
            "nir",
            "lack_of_nir_reason",
            "title",
            "first_name",
            "last_name",
            "birthdate",
        ]


class CreateOrUpdateJobSeekerStep2Form(MandatoryAddressFormMixin, forms.ModelForm):
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
                self.cleaned_data["lack_of_pole_emploi_id_reason"] = User.REASON_FORGOTTEN
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
            self.cleaned_data["lack_of_pole_emploi_id_reason"] = User.REASON_NOT_REGISTERED

        # Handle RSA extra fields
        if self.cleaned_data["rsa_allocation"]:
            if not self.cleaned_data["has_rsa_allocation"]:
                self.add_error(
                    "has_rsa_allocation",
                    forms.ValidationError("La majoration RSA est obligatoire"),
                )
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

    def __init__(self, siae, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["selected_jobs"].queryset = (
            siae.job_description_through.active().with_annotation_is_popular().prefetch_related("appellation")
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


class SubmitJobApplicationForm(forms.ModelForm, ResumeFormMixin):
    """
    Submit a job application to an SIAE.
    """

    def __init__(self, siae, user, *args, **kwargs):
        self.siae = siae
        super().__init__(*args, **kwargs)
        self.fields["selected_jobs"].queryset = siae.job_description_through.filter(is_active=True)

        self.fields["message"].required = not user.is_siae_staff
        self.fields["message"].widget.attrs["placeholder"] = ""
        if user.is_job_seeker:
            self.fields["message"].label = "Message à l’employeur"
            help_text = "Message obligatoire à destination de l’employeur et non modifiable après l’envoi."
        elif user.is_siae_staff:
            self.fields["message"].label = "Message d’information"
            help_text = "Ce message ne sera plus modifiable après l’envoi et une copie sera transmise au candidat."
        else:
            self.fields["message"].label = "Message à l’employeur (avec copie transmise au candidat)"
            help_text = "Message obligatoire et non modifiable après l’envoi."
        self.fields["message"].help_text = help_text

    class Meta:
        model = JobApplication
        fields = ["selected_jobs", "message"] + ResumeFormMixin.Meta.fields
        widgets = {"selected_jobs": forms.CheckboxSelectMultiple()}
        labels = {"selected_jobs": "Métiers recherchés"}


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
        if job_application.to_siae.kind == SiaeKind.GEIQ:
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
    If SIAE is a GEIQ, add specific fields (contract type, number of hours per week)
    """

    GEIQ_REQUIRED_FIELDS = (
        "prehiring_guidance_days",
        "contract_type",
        "contract_type_details",
        "nb_hours_per_week",
        "qualification_type",
        "qualification_level",
        "planned_training_days",
    )

    # Choices are dynamically set on HTMX reload
    qualification_level = forms.ChoiceField(choices=[], label="Niveau de qualification")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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

        if job_application := kwargs.get("instance"):
            is_geiq = job_application.to_siae.kind == SiaeKind.GEIQ
            # Remove or make GEIQ specific fields mandatory
            for geiq_field_name in self.GEIQ_REQUIRED_FIELDS:
                if is_geiq:
                    # Contract type details are dynamic and not required all the time
                    self.fields[geiq_field_name].required = geiq_field_name != "contract_type_details"
                else:
                    self.fields.pop(geiq_field_name)

            if is_geiq:
                # Change default size (too large)
                self.fields["contract_type_details"].widget.attrs.update({"rows": 2})
                self.initial["prehiring_guidance_days"] = 0
                self.initial["planned_training_days"] = 0
                self.fields["hiring_start_at"].help_text = "Au format JJ/MM/AAAA, par exemple  %(date)s."
                # Dynamic selection of qualification level
                self.fields["qualification_type"].widget.attrs.update(
                    {
                        "hx-post": reverse(
                            "apply:reload_qualification_fields", kwargs={"job_application_id": job_application.pk}
                        ),
                        "hx-swap": "outerHTML show:#id_qualification_type:top",
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
            else:
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

    class Meta:
        model = JobApplication
        fields = [
            "prehiring_guidance_days",
            "contract_type",
            "contract_type_details",
            "nb_hours_per_week",
            "hiring_start_at",
            "qualification_type",
            "planned_training_days",
            "hiring_end_at",
            "answer",
        ]
        help_texts = {
            # Make it clear to employers that `hiring_start_at` has an impact on the start of the
            # "parcours IAE" and the payment of the "aide au poste".
            "hiring_start_at": "Au format JJ/MM/AAAA, par exemple  %(date)s. "
            "Il n'est pas possible d'antidater un contrat." % {"date": datetime.date.today().strftime("%d/%m/%Y")},
            "hiring_end_at": "Au format JJ/MM/AAAA, par exemple  %(date)s."
            % {
                "date": (datetime.date.today() + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)).strftime(
                    "%d/%m/%Y"
                )
            },
            "prehiring_guidance_days": """Laissez "0" si vous n'avez pas accompagné le candidat avant son embauche""",
            "planned_training_days": """Laissez "0" si vous n'avez pas prévu de jours de formation pour le candidat""",
            "contract_type_details": (
                "Si vous avez choisi un autre type de contrat, merci de bien vouloir fournir plus de précisions"
            ),
        }

    def clean_hiring_start_at(self):
        hiring_start_at = self.cleaned_data["hiring_start_at"]

        # Hiring in the past is *temporarily* possible for GEIQ
        if hiring_start_at and hiring_start_at < datetime.date.today() and self.instance.to_siae.kind != SiaeKind.GEIQ:
            raise forms.ValidationError(JobApplication.ERROR_START_IN_PAST)

        return hiring_start_at

    def clean(self):
        cleaned_data = super().clean()

        hiring_start_at = self.cleaned_data.get("hiring_start_at")
        hiring_end_at = self.cleaned_data.get("hiring_end_at")

        if hiring_end_at and hiring_start_at and hiring_end_at < hiring_start_at:
            raise forms.ValidationError(JobApplication.ERROR_END_IS_BEFORE_START)

        if self.instance.to_siae.kind == SiaeKind.GEIQ:
            # This validation is enforced by database constraints,
            # but we are nice enough to display a warning message to the user
            # (constraints violation message are generic)
            contract_type = self.cleaned_data.get("contract_type")
            contract_type_details = self.cleaned_data.get("contract_type_details")

            if contract_type == ContractType.OTHER and not contract_type_details:
                raise forms.ValidationError(
                    {"contract_type_details": ["Les précisions sont nécessaires pour ce type de contrat"]}
                )

        return cleaned_data


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


class JobSeekerPersonalDataForm(JobSeekerNIRUpdateMixin, forms.ModelForm):
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
        fields = ["nir", "lack_of_nir_reason", "birthdate", "pole_emploi_id", "lack_of_pole_emploi_id_reason"]
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
        filters = {}
        data = self.cleaned_data

        if data.get("states"):
            filters["state__in"] = data.get("states")
        if data.get("pass_iae_suspended"):
            # Filter on the `has_suspended_approval` annotation, which is set in `with_list_related_data()`.
            filters["has_suspended_approval"] = True
        if data.get("pass_iae_active"):
            # Simplification of CommonApprovalQuerySet.valid_lookup()
            filters["approval__end_at__gte"] = timezone.localdate()
            # The date is not enough to know if an approval is valid or not
            filters["has_suspended_approval"] = False
        if data.get("eligibility_validated"):
            filters["jobseeker_eligibility_diagnosis__isnull"] = False
        if data.get("start_date"):
            filters["created_at__gte"] = data.get("start_date")
        if data.get("end_date"):
            filters["created_at__lte"] = data.get("end_date")
        if data.get("departments"):
            filters["job_seeker__department__in"] = data.get("departments")
        if data.get("selected_jobs"):
            filters["selected_jobs__appellation__code__in"] = data.get("selected_jobs")
        if data.get("criteria"):
            # Filter on the `eligibility_diagnosis_criterion_{criterion}` annotation,
            # which is set in `with_list_related_data()`.
            for criterion in data.get("criteria"):
                filters[f"eligibility_diagnosis_criterion_{criterion}"] = True

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
        return sorted(users, key=lambda l: l[1])

    def _get_choices_for_administrativecriteria(self):
        return [(c.pk, c.name) for c in AdministrativeCriteria.objects.all()]

    def _get_choices_for_departments(self, job_seekers):
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
        required=False,
        label="Nom de l'organisme prescripteur",
        widget=Select2MultipleWidget,
    )

    def __init__(self, job_applications_qs, siae, *args, **kwargs):
        super().__init__(job_applications_qs, *args, **kwargs)
        self.fields["sender_organizations"].choices += self.get_sender_organization_choices()

        if siae.kind not in SIAE_WITH_CONVENTION_KINDS:
            del self.fields["eligibility_validated"]

        if not siae.can_have_prior_action:
            # Drop "pré-embauche" state from filter for non-GEIQ SIAE
            self.fields["states"].choices = [
                (k, v) for k, v in self.fields["states"].choices if k != JobApplicationWorkflow.STATE_PRIOR_TO_HIRE
            ]

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


class CheckJobSeekerGEIQEligibilityForm(forms.Form):
    choice = forms.BooleanField(required=False, widget=forms.RadioSelect(choices=((True, "Oui"), (False, "Non"))))
    back_url = forms.CharField(widget=forms.HiddenInput)
    next_url = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, job_application, back_url, next_url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["choice"].widget.attrs.update(
            {"hx-post": reverse("apply:geiq_eligibility", kwargs={"job_application_id": job_application.pk})}
        )
        self.fields["back_url"].initial = back_url
        self.fields["next_url"].initial = next_url
