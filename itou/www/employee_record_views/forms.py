from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, RegexValidator
from django.urls import reverse_lazy

from itou.asp.models import Commune, RSAAllocation
from itou.employee_record.models import EmployeeRecord
from itou.siaes.models import SiaeFinancialAnnex
from itou.users.models import JobSeekerProfile, User
from itou.utils.validators import validate_pole_emploi_id
from itou.utils.widgets import DuetDatePickerWidget


# Endpoint for INSEE communes autocomplete
COMMUNE_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:communes")


class SelectEmployeeRecordStatusForm(forms.Form):

    # The user is only able to select a subset of the possible
    # employee record statuses.
    # The other ones are internal only.
    STATUSES = [
        EmployeeRecord.Status.NEW,
        EmployeeRecord.Status.READY,
        EmployeeRecord.Status.SENT,
        EmployeeRecord.Status.REJECTED,
        EmployeeRecord.Status.PROCESSED,
    ]

    STATUS_CHOICES = [(choice.name, choice.label) for choice in STATUSES]
    status = forms.ChoiceField(
        widget=forms.RadioSelect(),
        choices=STATUS_CHOICES,
        initial=EmployeeRecord.Status.NEW,
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

    # FIXME:
    # `data-period-date` class attribute should not be on this component
    # but on `DuetDatePickerWidget`
    # For the moment :
    # - adding custom classes attrs via `widget.attrs` on datepicker does not work
    # - keep using the autocomplete as "holder" of the period information
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.REQUIRED_FIELDS:
            self.fields[field_name].required = True

        self.fields["birthdate"].widget = DuetDatePickerWidget(
            {
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )
        self.fields["birthdate"].widget.attrs = {"class": "js-period-date-input"}

        # Init ASP commune
        if self.instance.birth_place:
            self.initial[
                "insee_commune"
            ] = f"{self.instance.birth_place.name} ({self.instance.birth_place.department_code})"
            self.initial["insee_commune_code"] = self.instance.birth_place.code

    def clean_insee_commune_code(self):
        commune_code = self.cleaned_data["insee_commune_code"]

        if commune_code and not Commune.objects.current().by_insee_code(commune_code).exists():
            raise ValidationError("Cette commune n'existe pas ou n'est pas référencée")

        return commune_code

    def clean(self):
        super().clean()

        commune_code = self.cleaned_data["insee_commune_code"]

        if commune_code:
            self.cleaned_data["birth_place"] = Commune.objects.current().by_insee_code(commune_code).first()

    class Meta:
        model = User
        fields = [
            "title",
            "first_name",
            "last_name",
            "birthdate",
            "insee_commune",
            "insee_commune_code",
            "birth_place",
            "birth_country",
        ]


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
            message="Le champ ne doit pas contenir de caractères spéciaux et ne pas excéder 32 caractères",
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
            raise ValidationError("L'extension doit être saisie avec un numéro de voie")

        commune_code = self.cleaned_data.get("insee_commune_code")
        post_code = self.cleaned_data.get("hexa_post_code")

        # Check basic coherence between post-code and INSEE code:
        if post_code and commune_code and post_code[:2] != commune_code[:2]:
            raise ValidationError("Le code postal ne correspond pas à la commune")

        if commune_code:
            commune = Commune.objects.current().by_insee_code(commune_code).first()
            self.cleaned_data["hexa_commune"] = commune

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


class NewEmployeeRecordStep3Form(forms.ModelForm):
    """
    New employee record step 3:

    - situation of employee
    - social allowances
    """

    pole_emploi = forms.BooleanField(required=False, label="Le salarié est-il inscrit à Pôle emploi ?")
    pole_emploi_id = forms.CharField(
        label="Identifiant Pôle emploi",
        required=False,
        validators=[validate_pole_emploi_id, MinLengthValidator(8)],
    )

    # A set of transient checkboxes used to collapse optional blocks
    rsa_allocation = forms.BooleanField(required=False, label="Le salarié est-il bénéficiaire du RSA ?")
    ass_allocation = forms.BooleanField(required=False, label="Le salarié est-il bénéficiaire de l'ASS ?")
    aah_allocation = forms.BooleanField(required=False, label="Le salarié est-il bénéficiaire de l'AAH ?")
    unemployed = forms.BooleanField(required=False, label="Le salarié était-il sans emploi à l'embauche ?")

    # This field is a subset of the possible choices of `has_rsa_allocation` model field
    rsa_markup = forms.ChoiceField(required=False, label="Majoration du RSA", choices=RSAAllocation.choices[1:])

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
            "resourceless": "Salarié sans ressource ?",
            "pole_emploi_since": "Inscrit depuis",
            "has_rsa_allocation": "Le salarié est-il bénéficiaire du RSA ?",
        }


class NewEmployeeRecordStep4(forms.Form):
    """
    New employee record step 4:

    select a valid financial annex
    """

    financial_annex = forms.ModelChoiceField(
        queryset=None,
        label="Annexe financière",
        help_text="Vous devez rattacher la fiche salarié à une annexe financière validée ou provisoire",
    )

    def __init__(self, employee_record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.employee_record = employee_record

        # Fetch active financial annexes for the SIAE
        convention = employee_record.job_application.to_siae.convention
        self.fields["financial_annex"].queryset = convention.financial_annexes.filter(
            state__in=SiaeFinancialAnnex.STATES_ACTIVE
        )

    def clean(self):
        super().clean()

        self.employee_record.financial_annex = self.cleaned_data["financial_annex"]
