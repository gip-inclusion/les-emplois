from django import forms
from django.db.models import OuterRef, Q, Subquery
from django.forms import ValidationError
from django.utils import timezone
from django.utils.html import format_html
from django_select2.forms import Select2Widget

from itou.approvals.models import Approval
from itou.asp import models as asp_models
from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.common_apps.nir.forms import JobSeekerNIRUpdateMixin
from itou.users.enums import LackOfPoleEmploiId, UserKind
from itou.users.forms import JobSeekerProfileFieldsMixin, JobSeekerProfileModelForm
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.emails import redact_email_address
from itou.utils.templatetags.str_filters import mask_unless
from itou.utils.validators import validate_nir
from itou.utils.widgets import DuetDatePickerWidget


class FilterForm(forms.Form):
    job_seeker = forms.ChoiceField(
        required=False,
        label="Nom",
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom du candidat",
            }
        ),
    )

    eligibility_validated = forms.BooleanField(label="Valide", required=False)
    eligibility_pending = forms.BooleanField(label="À valider", required=False)

    pass_iae_active = forms.BooleanField(label="Valide", required=False)
    pass_iae_expired = forms.BooleanField(label="Expiré", required=False)
    no_pass_iae = forms.BooleanField(label="Aucun", required=False)

    def __init__(self, job_seeker_qs, data, *args, request_user, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.fields["job_seeker"].choices = [
            (
                job_seeker.pk,
                mask_unless(
                    job_seeker.get_full_name(), predicate=request_user.can_view_personal_information(job_seeker)
                ),
            )
            for job_seeker in job_seeker_qs.order_by("first_name", "last_name")
            if job_seeker.get_full_name()
        ]

    def get_filters_counter(self):
        return sum(bool(self.cleaned_data.get(field.name)) for field in self)

    def filter(self, queryset):
        filters = []

        if job_seeker_id := self.cleaned_data.get("job_seeker"):
            filters.append(Q(pk=job_seeker_id))

        # Eligibility status (all checkboxes checked = all cases, so do not filter out results)
        if self.cleaned_data.get("eligibility_validated") and not self.cleaned_data.get("eligibility_pending"):
            queryset = queryset.eligibility_validated()
        elif self.cleaned_data.get("eligibility_pending") and not self.cleaned_data.get("eligibility_validated"):
            queryset = queryset.eligibility_pending()

        # Approval (PASS IAE) status (all checkboxes checked = all cases, so do not filter out results)
        pass_iae_filters = [
            self.cleaned_data.get(key) for key in ("pass_iae_active", "pass_iae_expired", "no_pass_iae")
        ]
        if any(pass_iae_filters) and not all(pass_iae_filters):
            last_approval_end_at = Subquery(
                Approval.objects.filter(user=OuterRef("pk")).order_by("-end_at").values("end_at")[:1]
            )
            queryset = queryset.annotate(last_approval_end_at=last_approval_end_at)

            pass_status_filter = Q()
            if self.cleaned_data.get("pass_iae_active"):
                pass_status_filter |= Q(last_approval_end_at__gte=timezone.localdate())
            if self.cleaned_data.get("pass_iae_expired"):
                pass_status_filter |= Q(last_approval_end_at__lt=timezone.localdate())
            if self.cleaned_data.get("no_pass_iae"):
                pass_status_filter |= Q(last_approval_end_at__isnull=True)
            filters.append(pass_status_filter)

        return queryset.filter(*filters)


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

    def __init__(self, *args, job_seeker=None, is_gps=False, **kwargs):
        self.job_seeker = job_seeker
        super().__init__(*args, **kwargs)
        if self.job_seeker:
            self.fields["nir"].label = "Votre numéro de sécurité sociale"
        else:
            self.fields["nir"].label = "Numéro de sécurité sociale du " + ("bénéficiaire" if is_gps else "candidat")

    def clean_nir(self):
        nir = self.cleaned_data["nir"].upper()
        nir = nir.replace(" ", "")
        existing_account = User.objects.filter(jobseeker_profile__nir=nir).first()

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


class JobSeekerExistsForm(forms.Form):
    def __init__(self, is_gps=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None

        if is_gps:
            self.fields["email"].label = "Adresse e-mail du bénéficiaire"

    email = forms.EmailField(
        label="Adresse e-mail personnelle du candidat",
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
                    "Vous ne pouvez pas postuler pour cet utilisateur car "
                    "cet e-mail est déjà rattaché à un prescripteur ou à un employeur."
                )
                raise forms.ValidationError(error)
        return email

    def get_user(self):
        return self.user


class CreateOrUpdateJobSeekerStep1Form(JobSeekerNIRUpdateMixin, JobSeekerProfileModelForm):
    PROFILE_FIELDS = ["birth_country", "birthdate", "birth_place", "nir", "lack_of_nir_reason"]

    class Meta(JobSeekerProfileModelForm.Meta):
        pass

    def clean(self):
        super().clean()
        JobSeekerProfile.clean_nir_title_birthdate_fields(self.cleaned_data)


class CreateOrUpdateJobSeekerStep2Form(JobSeekerAddressForm, forms.ModelForm):
    class Meta(JobSeekerAddressForm.Meta):
        fields = JobSeekerAddressForm.Meta.fields + ["phone"]
        widgets = {"phone": forms.TextInput(attrs={"type": "tel"})}


class CreateOrUpdateJobSeekerStep3Form(forms.ModelForm):
    # A set of transient checkboxes used to collapse optional blocks
    pole_emploi = forms.BooleanField(required=False, label="Inscrit à France Travail")
    unemployed = forms.BooleanField(required=False, label="Sans emploi")
    rsa_allocation = forms.BooleanField(required=False, label="Bénéficiaire du RSA")
    ass_allocation = forms.BooleanField(required=False, label="Bénéficiaire de l'ASS")
    aah_allocation = forms.BooleanField(required=False, label="Bénéficiaire de l'AAH")

    pole_emploi_id_forgotten = forms.BooleanField(required=False, label="Identifiant France Travail oublié")

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
            "pole_emploi_id",
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
            "pole_emploi": "La durée d'inscription à France Travail est obligatoire",
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
                    forms.ValidationError("L'identifiant France Travail est obligatoire"),
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


class CheckJobSeekerInfoForm(JobSeekerProfileFieldsMixin, forms.ModelForm):
    PROFILE_FIELDS = ["birthdate", "pole_emploi_id", "lack_of_pole_emploi_id_reason"]

    class Meta:
        model = User
        fields = [
            "phone",
        ]
        help_texts = {
            "birthdate": "Au format JJ/MM/AAAA, par exemple 20/12/1978.",
        }
        widgets = {"phone": forms.TextInput(attrs={"type": "tel"})}

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
        JobSeekerProfile.clean_pole_emploi_fields(self.cleaned_data)
        JobSeekerProfile.clean_nir_title_birthdate_fields(
            self.cleaned_data | {"nir": self.instance.jobseeker_profile.nir}, remind_nir_in_error=True
        )
