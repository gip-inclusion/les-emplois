from django import forms
from django.core.validators import MinLengthValidator
from django.urls import reverse_lazy

from itou.asp.models import Commune, RSAAllocation
from itou.employee_record.models import EmployeeRecord
from itou.siaes.models import SiaeFinancialAnnex
from itou.users.models import JobSeekerProfile, User
from itou.utils.validators import validate_pole_emploi_id
from itou.utils.widgets import DatePickerField


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


class NewEmployeeRecordStep1(forms.ModelForm):
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

        if hasattr(self, "instance"):
            # Init for with ASP commune
            if self.instance.birth_place:
                self.initial[
                    "insee_commune"
                ] = f"{self.instance.birth_place.name} ({self.instance.birth_place.department_code})"
                self.initial["insee_commune_code"] = self.instance.birth_place.code

    def clean(self):
        super().clean()

        commune_code = self.cleaned_data["insee_commune_code"]

        if commune_code:
            self.cleaned_data["birth_place"] = Commune.objects.by_insee_code(commune_code)

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


class NewEmployeeRecordStep2(forms.ModelForm):
    """
    New employee record step 2:
    - HEXA address lookup
    - details of the employee
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in ["phone", "email"]:
            self.fields[field_name].widget.attrs["readonly"] = True
            self.fields[field_name].help_text = "Champs non-modifiable"

    class Meta:
        model = User
        fields = [
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "phone",
            "email",
        ]


class NewEmployeeRecordStep3(forms.ModelForm):
    """
    New employee record step 3:
    - situation of employee and details
    """

    pole_emploi = forms.BooleanField(required=False, label="Le salarié est-il inscrit à Pôle emploi ?")
    pole_emploi_id = forms.CharField(
        label="Identifiant Pôle emploi",
        required=False,
        validators=[validate_pole_emploi_id, MinLengthValidator(8)],
    )

    # A set of transient checkboxes used to fold/unfold options on display
    rsa_allocation = forms.BooleanField(required=False, label="Le salarié est-il bénéficiaire du RSA ?")
    ass_allocation = forms.BooleanField(required=False, label="Le salarié est-il bénéficiaire de l'ASS ?")
    aah_allocation = forms.BooleanField(required=False, label="Le salarié est-il bénéficiaire de l'AAH ?")
    ata_allocation = forms.BooleanField(required=False, label="Le salarié est-il bénéficiaire de l'ATA ?")

    # This field is a subset of the possible choices of `has_rsa_allocation` model field
    rsa_markup = forms.ChoiceField(required=False, label="Majoration du RSA", choices=RSAAllocation.choices[1:])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Pôle emploi
        pole_emploi_id = self.instance.user.pole_emploi_id
        if pole_emploi_id:
            self.initial["pole_emploi_id"] = pole_emploi_id
            self.initial["pole_emploi"] = True
            self.fields["pole_emploi_id"].widget.attrs["readonly"] = True
        self.fields["pole_emploi"].widget.attrs["onclick"] = "toggleFold(this)"

        # Foldable sections
        for field in ["rsa_allocation", "ass_allocation", "aah_allocation", "ata_allocation"]:
            self.fields[field].widget.attrs["onclick"] = "toggleFold(this)"
            self.initial[field] = getattr(self.instance, field + "_since")

        # RSA Markup
        self.initial["rsa_markup"] = self.instance.has_rsa_allocation

    def clean(self):
        super().clean()

        # Pôle emploi
        if self.cleaned_data["pole_emploi"]:
            if not self.cleaned_data["pole_emploi_since"]:
                raise forms.ValidationError("La durée d'inscription à Pôle emploi est obligatoire")

            if not self.cleaned_data["pole_emploi_id"]:
                raise forms.ValidationError("L'identifiant Pôle emploi est obligatoire")

        # RSA
        if self.cleaned_data["rsa_allocation"]:
            # If checked, all fields must be filled
            if not (self.cleaned_data["rsa_allocation_since"] and self.cleaned_data["rsa_markup"]):
                raise forms.ValidationError("La durée d'inscription et la majoration RSA sont obligatoires")

    def save(self, *args, **kwargs):
        if self.cleaned_data["rsa_allocation"]:
            self.instance.has_rsa_allocation = self.cleaned_data["rsa_markup"]

        super().save(*args, **kwargs)

    class Meta:
        model = JobSeekerProfile
        fields = [
            "education_level",
            "resourceless",
            "pole_emploi_since",
            "rqth_employee",
            "oeth_employee",
            "rsa_allocation_since",
            "ass_allocation_since",
            "aah_allocation_since",
            "ata_allocation_since",
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
    Select a valid financial annex
    """

    financial_annex = forms.ChoiceField(
        choices=[],
        label="Annexe financière",
        help_text="Vous devez rattacher la fiche salarié à une annexe financière validée ou provisoire",
    )

    def __init__(self, employee_record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.employee_record = employee_record

        # Fetch active financial annexes for the SIAE
        convention = employee_record.job_application.to_siae.convention
        financial_annexes = convention.financial_annexes.filter(state__in=SiaeFinancialAnnex.STATES_ACTIVE)

        choices = [(annex.number, annex.number) for annex in financial_annexes]
        self.fields["financial_annex"].choices = choices

    def clean(self):
        super().clean()

        self.employee_record.financial_annex = SiaeFinancialAnnex.objects.get(
            number=self.cleaned_data["financial_annex"]
        )
