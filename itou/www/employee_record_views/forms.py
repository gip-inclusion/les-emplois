from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, RegexValidator
from django.urls import reverse_lazy
from django.utils import timezone
from django_select2.forms import Select2MultipleWidget

from itou.asp.exceptions import CommuneUnknownInPeriodError, UnknownCommuneError
from itou.asp.models import Commune, Country, RSAAllocation
from itou.companies.models import SiaeFinancialAnnex
from itou.employee_record.enums import Status
from itou.users.models import JobSeekerProfile, User
from itou.utils.validators import validate_pole_emploi_id
from itou.utils.widgets import DuetDatePickerWidget

from .enums import EmployeeRecordOrder


# Endpoint for INSEE communes autocomplete
COMMUNE_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:communes")


class SelectEmployeeRecordStatusForm(forms.Form):
    # The user is only able to select a subset of the possible
    # employee record statuses.
    # The other ones are internal only.
    STATUSES = [
        Status.NEW,
        Status.READY,
        Status.SENT,
        Status.REJECTED,
        Status.PROCESSED,
        Status.DISABLED,
    ]

    STATUS_CHOICES = [(choice.name, choice.label) for choice in STATUSES]
    status = forms.ChoiceField(
        widget=forms.RadioSelect(),
        choices=STATUS_CHOICES,
        initial=Status.NEW,
        required=False,
    )

    order = forms.ChoiceField(
        widget=forms.RadioSelect(),
        choices=EmployeeRecordOrder.choices,
        initial=EmployeeRecordOrder.HIRING_START_AT_DESC,
        required=False,
    )


class EmployeeRecordFilterForm(forms.Form):
    job_seekers = forms.MultipleChoiceField(
        required=False,
        label="Nom du candidat",
        widget=Select2MultipleWidget,
    )

    def __init__(self, job_seekers, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["job_seekers"].choices = sorted(
            [(user.id, user.get_full_name().title()) for user in job_seekers if user.get_full_name()],
            key=lambda u: u[1],
        )


class NewEmployeeRecordStep1Form(forms.ModelForm):
    """
    New employee record step 1:
    - main details (just check)
    - birth place and birth country of the employee
    """

    COMMUNE_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:communes")

    READ_ONLY_FIELDS = []
    REQUIRED_FIELDS = [
        "title",
        "first_name",
        "last_name",
        "birthdate",
        "birth_country",
    ]

    insee_commune = forms.CharField(
        label="Commune de naissance",
        required=False,
        help_text="La commune de naissance ne doit être saisie que lorsque le salarié est né en France",
        widget=forms.TextInput(
            attrs={
                "class": "js-commune-autocomplete-input form-control",
                "data-autocomplete-source-url": COMMUNE_AUTOCOMPLETE_SOURCE_URL,
                "data-period-date": "birthdate",
                "data-autosubmit-on-enter-pressed": 0,
                "placeholder": "Nom de la commune",
                "autocomplete": "off",
            }
        ),
    )
    insee_commune_code = forms.CharField(
        required=False, widget=forms.HiddenInput(attrs={"class": "js-commune-autocomplete-hidden"})
    )

    # This is a JobSeekerProfile field
    birth_country = forms.ModelChoiceField(Country.objects, label="pays de naissance")

    class Meta:
        model = User
        fields = [
            "title",
            "first_name",
            "last_name",
            "birthdate",
            "insee_commune",
            "insee_commune_code",
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

        jobseeker_profile = self.instance.jobseeker_profile

        if jobseeker_profile.birth_place:
            self.initial[
                "insee_commune"
            ] = f"{jobseeker_profile.birth_place.name} ({jobseeker_profile.birth_place.department_code})"
            self.initial["insee_commune_code"] = jobseeker_profile.birth_place.code

        if jobseeker_profile.birth_country:
            self.initial["birth_country"] = jobseeker_profile.birth_country_id

    def clean(self):
        super().clean()

        commune_code = self.cleaned_data.get("insee_commune_code")
        birth_date = self.cleaned_data.get("birthdate")

        # Country coherence is done at model level (users.User)
        # Here we must add coherence between birthdate and communes
        # existing at this period (not a simple check of existence)

        if commune_code and birth_date:
            try:
                self.cleaned_data["birth_place"] = Commune.by_insee_code_and_period(commune_code, birth_date)
            except CommuneUnknownInPeriodError as ex:
                raise forms.ValidationError(
                    f"Le code INSEE {commune_code} n'est pas référencé en date du {birth_date:%d/%m/%Y}"
                ) from ex

    def _post_clean(self):
        super()._post_clean()
        jobseeker_profile = self.instance.jobseeker_profile
        try:
            jobseeker_profile.birth_place = self.cleaned_data.get("birth_place")
            jobseeker_profile.birth_country = self.cleaned_data.get("birth_country")
            jobseeker_profile._clean_birth_fields()
        except ValidationError as e:
            self._update_errors(e)

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            jobseeker_profile = self.instance.jobseeker_profile
            # Fields were updated in _post_clean()
            jobseeker_profile.save(update_fields=("birth_place", "birth_country"))
        return instance


class NewEmployeeRecordStep2Form(forms.ModelForm):
    """
    If the geolocation of address fails, allows user to manually enter
    an address based on ASP internal address format.
    These fields are *not* mapped directly to a JobSeekerProfile object,
    mainly because of model level validation concerns (model.clean method)
    """

    insee_commune = forms.CharField(
        label="Commune",
        widget=forms.TextInput(
            attrs={
                "class": "js-commune-autocomplete-input form-control",
                "data-autocomplete-source-url": COMMUNE_AUTOCOMPLETE_SOURCE_URL,
                "data-autosubmit-on-enter-pressed": 0,
                "placeholder": "Nom de la commune",
                "autocomplete": "off",
            }
        ),
    )
    insee_commune_code = forms.CharField(widget=forms.HiddenInput(attrs={"class": "js-commune-autocomplete-hidden"}))

    class Meta:
        model = JobSeekerProfile
        fields = [
            "hexa_lane_type",
            "hexa_lane_number",
            "hexa_std_extension",
            "hexa_lane_name",
            "hexa_additional_address",
            "hexa_post_code",
            "hexa_commune",
        ]
        labels = {
            "hexa_lane_number": "Numéro",
            "hexa_std_extension": "Extension",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["hexa_lane_type"].required = True
        self.fields["hexa_lane_name"].required = True
        self.fields["hexa_post_code"].required = True

        # Adding RE validators for ASP constraints
        self.fields["hexa_lane_number"].validators = [
            RegexValidator("^[0-9]{,5}$", message="Numéro de voie incorrect")
        ]

        self.fields["hexa_post_code"].validators = [RegexValidator("^[0-9]{5}$", message="Code postal incorrect")]

        address_re_validator = RegexValidator(
            "^[a-zA-Z0-9@ ]{,32}$",
            message="Le champ ne doit contenir ni caractères spéciaux, ni accents et ne pas excéder 32 caractères",
        )
        self.fields["hexa_lane_name"].validators = [address_re_validator]
        self.fields["hexa_additional_address"].validators = [address_re_validator]

        # Pre-fill INSEE commune
        if self.instance.hexa_commune:
            self.initial[
                "insee_commune"
            ] = f"{self.instance.hexa_commune.name} ({self.instance.hexa_commune.department_code})"
            self.initial["insee_commune_code"] = self.instance.hexa_commune.code

    def clean(self):
        super().clean()

        if self.cleaned_data.get("hexa_std_extension") and not self.cleaned_data.get("hexa_lane_number"):
            raise forms.ValidationError("L'extension doit être saisie avec un numéro de voie")

        commune_code = self.cleaned_data.get("insee_commune_code")
        post_code = self.cleaned_data.get("hexa_post_code")

        # Check basic coherence between post-code and INSEE code:
        if post_code and commune_code and post_code[:2] != commune_code[:2]:
            raise forms.ValidationError("Le code postal ne correspond pas à la commune")

        if commune_code:
            try:
                commune = Commune.by_insee_code(commune_code)
            except UnknownCommuneError:
                raise forms.ValidationError(f"Le code INSEE {commune_code} n'est pas référencé")
            else:
                self.cleaned_data["hexa_commune"] = commune


class NewEmployeeRecordStep3Form(forms.ModelForm):
    """
    New employee record step 3:

    - situation of employee
    - social allowances
    """

    pole_emploi = forms.BooleanField(required=False, label="Inscrit à Pôle emploi ?")
    pole_emploi_id = forms.CharField(
        label="Identifiant Pôle emploi",
        required=False,
        validators=[validate_pole_emploi_id, MinLengthValidator(8)],
    )

    # A set of transient checkboxes used to collapse optional blocks
    rsa_allocation = forms.BooleanField(
        required=False,
        label="Bénéficiaire du RSA",
        help_text="Revenu de solidarité active",
    )
    ass_allocation = forms.BooleanField(
        required=False,
        label="Bénéficiaire de l'ASS ?",
        help_text="Allocation de solidarité spécifique",
    )
    aah_allocation = forms.BooleanField(
        required=False,
        label="Bénéficiaire de l'AAH ?",
        help_text="Allocation aux adultes handicapés",
    )
    unemployed = forms.BooleanField(required=False, label="Sans emploi à l'embauche ?")

    # This field is a subset of the possible choices of `has_rsa_allocation` model field
    rsa_markup = forms.ChoiceField(required=False, label="Majoration du RSA", choices=RSAAllocation.choices[1:])

    class Meta:
        model = JobSeekerProfile
        fields = [
            "education_level",
            "resourceless",
            "pole_emploi_since",
            "unemployed_since",
            "rqth_employee",
            "oeth_employee",
            "rsa_allocation_since",
            "ass_allocation_since",
            "aah_allocation_since",
        ]
        labels = {
            "education_level": "Niveau de formation",
            "resourceless": "Sans ressource ?",
            "pole_emploi_since": "Inscrit depuis",
            "has_rsa_allocation": "Bénéficiaire du RSA ?",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Collapsible sections:
        # If these non-model fields are checked, matching model fields are updatable
        # otherwise model fields reset to empty value ("")
        for field in ["unemployed", "rsa_allocation", "ass_allocation", "aah_allocation"]:
            self.initial[field] = getattr(self.instance, field + "_since")

        # Pôle emploi (collapsible section)
        pole_emploi_id = self.instance.user.pole_emploi_id

        if pole_emploi_id:
            self.initial["pole_emploi_id"] = pole_emploi_id
            self.initial["pole_emploi"] = True
            self.fields["pole_emploi_id"].widget.attrs["readonly"] = True

        # RSA Markup (collapsible section)
        self.initial["rsa_markup"] = self.instance.has_rsa_allocation

        # "Standard" model field
        self.fields["education_level"].required = True

    def clean(self):
        super().clean()

        # Pôle emploi
        if self.instance.user.pole_emploi_id:
            if not self.cleaned_data["pole_emploi_since"]:
                raise forms.ValidationError("La durée d'inscription à Pôle emploi est obligatoire")

            if not self.cleaned_data.get("pole_emploi_id"):
                # This field is validated and may not exist in `cleaned_data`
                raise forms.ValidationError("L'identifiant Pôle emploi est obligatoire")

            self.instance.user.pole_emploi_id = self.cleaned_data["pole_emploi_id"]
            self.instance.user.save()
        else:
            # Reset "inner" fields
            self.cleaned_data["pole_emploi_since"] = self.cleaned_data["pole_emploi_id"] = ""

        # RSA: 3 possible options, one is handled by `rsa_allocation` value
        if self.cleaned_data["rsa_allocation"]:
            # If checked, all fields must be filled
            if not (self.cleaned_data["rsa_allocation_since"] and self.cleaned_data["rsa_markup"]):
                raise forms.ValidationError("La durée d'inscription et la majoration RSA sont obligatoires")
        else:
            # Reset "inner" fields
            self.cleaned_data["rsa_allocation_since"] = self.cleaned_data["rsa_markup"] = ""
            self.instance.has_rsa_allocation = RSAAllocation.NO

        # Collapsible blocks field validation
        collapsible_errors = {
            "unemployed": "La période sans emploi est obligatoire",
            "ass_allocation": "La durée d'allocation de l'ASS est obligatoire",
            "aah_allocation": "La durée d'allocation de l'AAH est obligatoire",
        }

        for collapsible_field, error_message in collapsible_errors.items():
            inner_field_name = collapsible_field + "_since"
            if self.cleaned_data[collapsible_field]:
                if not self.cleaned_data[inner_field_name]:
                    raise forms.ValidationError(error_message)
            else:
                # Reset "inner" model fields, if non-model field unchecked
                self.cleaned_data[inner_field_name] = ""

    def save(self, *args, **kwargs):
        if self.cleaned_data["rsa_allocation"]:
            self.instance.has_rsa_allocation = self.cleaned_data["rsa_markup"]

        if self.cleaned_data["pole_emploi"]:
            self.instance.user.pole_emploi_id = self.cleaned_data["pole_emploi_id"]

        super().save(*args, **kwargs)


class NewEmployeeRecordStep4(forms.Form):
    """
    New employee record step 4:

    select a valid financial annex
    """

    financial_annex = forms.ModelChoiceField(
        queryset=None,
        label="Annexe financière",
        help_text="Vous pouvez rattacher la fiche salarié à une annexe financière validée ou provisoire",
    )

    def __init__(self, employee_record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.employee_record = employee_record

        # Fetch active financial annexes for the SIAE
        convention = employee_record.job_application.to_siae.convention
        self.fields["financial_annex"].queryset = convention.financial_annexes.filter(
            state__in=SiaeFinancialAnnex.STATES_ACTIVE, end_at__gt=timezone.now()
        )
        self.fields["financial_annex"].initial = employee_record.financial_annex
        self.fields["financial_annex"].required = False

    def clean(self):
        super().clean()

        self.employee_record.financial_annex = self.cleaned_data["financial_annex"]
