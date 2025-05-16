from django import forms
from django.core.validators import RegexValidator
from django.urls import reverse_lazy
from django_select2.forms import Select2Widget

from itou.asp.models import Commune, RSAAllocation
from itou.employee_record.enums import Status
from itou.users.models import JobSeekerProfile
from itou.utils.widgets import RemoteAutocompleteSelect2Widget
from itou.www.employee_record_views.enums import EmployeeRecordOrder


class AddEmployeeRecordChooseEmployeeForm(forms.Form):
    employee = forms.ChoiceField(
        required=True,
        label="Nom du salarié",
        widget=Select2Widget,
        help_text="Le salarié concerné par le transfert de données vers l'Extranet IAE 2.0 de l'ASP",
    )

    def __init__(self, employees, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["employee"].choices = [(None, "Sélectionnez le salarié")] + [
            (user.id, user.get_full_name()) for user in employees if user.get_full_name()
        ]


class FindEmployeeOrJobSeekerForm(AddEmployeeRecordChooseEmployeeForm):
    def __init__(self, employees, *args, **kwargs):
        super().__init__(employees=employees, *args, **kwargs)

        self.fields["employee"].help_text = ""


class AddEmployeeRecordChooseApprovalForm(forms.Form):
    approval = forms.ChoiceField(
        label="PASS IAE",
        required=True,
        help_text="Le PASS IAE concerné par le transfert de données vers l'Extranet IAE 2.0 de l'ASP",
    )

    def __init__(self, *args, employee, approvals, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["approval"].choices = [
            (approval.pk, f"{approval.number} — Du {approval.start_at:%d/%m/%Y} au {approval.end_at:%d/%m/%Y}")
            for approval in approvals
        ]
        self.fields["approval"].label = f"PASS IAE de {employee.get_full_name()}"


class SelectEmployeeRecordStatusForm(forms.Form):
    status = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        choices=Status.displayed_choices(),
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
    job_seeker = forms.TypedChoiceField(
        coerce=int,
        required=False,
        label="Nom du salarié",
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom du salarié",
            }
        ),
    )

    def __init__(self, job_seekers, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["job_seeker"].choices = sorted(
            [(user.id, user.get_full_name().title()) for user in job_seekers if user.get_full_name()],
            key=lambda u: u[1],
        )


class NewEmployeeRecordStep2Form(forms.ModelForm):
    """
    If the geolocation of address fails, allows user to manually enter
    an address based on ASP internal address format.
    """

    hexa_commune = forms.ModelChoiceField(
        queryset=Commune.objects,
        label="Commune",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": reverse_lazy("autocomplete:communes"),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 2,
                "data-placeholder": "Nom de la commune",
            },
        ),
    )

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

    def clean(self):
        super().clean()

        if self.cleaned_data.get("hexa_std_extension") and not self.cleaned_data.get("hexa_lane_number"):
            raise forms.ValidationError("L'extension doit être saisie avec un numéro de voie")

        hexa_commune = self.cleaned_data.get("hexa_commune")
        post_code = self.cleaned_data.get("hexa_post_code")

        # Check basic coherence between post-code and INSEE code:
        if post_code and hexa_commune and post_code[:2] != hexa_commune.code[:2]:
            raise forms.ValidationError("Le code postal ne correspond pas à la commune")


class NewEmployeeRecordStep3Form(forms.ModelForm):
    """
    New employee record step 3:

    - situation of employee
    - social allowances
    """

    pole_emploi = forms.BooleanField(required=False, label="Inscrit à France Travail")

    # A set of transient checkboxes used to collapse optional blocks
    rsa_allocation = forms.BooleanField(
        required=False,
        label="Bénéficiaire du RSA",
        help_text="Revenu de solidarité active",
    )
    ass_allocation = forms.BooleanField(
        required=False,
        label="Bénéficiaire de l'ASS",
        help_text="Allocation de solidarité spécifique",
    )
    aah_allocation = forms.BooleanField(
        required=False,
        label="Bénéficiaire de l'AAH",
        help_text="Allocation aux adultes handicapés",
    )
    unemployed = forms.BooleanField(required=False, label="Sans emploi à l'embauche")

    # This field is a subset of the possible choices of `has_rsa_allocation` model field
    rsa_markup = forms.ChoiceField(required=False, label="Majoration du RSA", choices=RSAAllocation.choices[1:])

    COLLAPSIBLE_SINCE_FIELDS = ["unemployed", "rsa_allocation", "ass_allocation", "aah_allocation"]
    COLLAPSIBLE_SINCE_FIELDS_ERRORS = {
        "unemployed": "La période sans emploi est obligatoire",
        "ass_allocation": "La durée d'allocation de l'ASS est obligatoire",
        "aah_allocation": "La durée d'allocation de l'AAH est obligatoire",
    }

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
            "rsa_allocation_since",
            "ass_allocation_since",
            "aah_allocation_since",
        ]
        labels = {
            "education_level": "Niveau de formation",
            "resourceless": "Sans ressource",
            "pole_emploi_since": "Inscrit depuis",
            "has_rsa_allocation": "Bénéficiaire du RSA",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Collapsible sections:
        # If these non-model fields are checked, matching model fields are updatable
        # otherwise model fields reset to empty value ("")
        for field in self.COLLAPSIBLE_SINCE_FIELDS:
            self.initial[field] = getattr(self.instance, field + "_since")

        # Pôle emploi (collapsible section)
        pole_emploi_id = self.instance.user.jobseeker_profile.pole_emploi_id
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
        if self.cleaned_data["pole_emploi"] or self.instance.user.jobseeker_profile.pole_emploi_id:
            if not self.cleaned_data["pole_emploi_since"]:
                raise forms.ValidationError("La durée d'inscription à France Travail est obligatoire")

            if not self.cleaned_data.get("pole_emploi_id"):
                # This field is validated and may not exist in `cleaned_data`
                raise forms.ValidationError("L'identifiant France Travail est obligatoire")
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
        for collapsible_field, error_message in self.COLLAPSIBLE_SINCE_FIELDS_ERRORS.items():
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
            self.instance.user.jobseeker_profile.pole_emploi_id = self.cleaned_data["pole_emploi_id"]

        super().save(*args, **kwargs)


class NewEmployeeRecordStep3ForEITIForm(NewEmployeeRecordStep3Form):
    are_allocation = forms.BooleanField(
        required=False,
        label="Bénéficiaire de l'ARE",
        help_text="Allocation d'aide au retour à l'emploi",
    )
    activity_bonus = forms.BooleanField(
        required=False,
        label="Bénéficiaire de la prime d'activité",
    )

    COLLAPSIBLE_SINCE_FIELDS = NewEmployeeRecordStep3Form.COLLAPSIBLE_SINCE_FIELDS + [
        "are_allocation",
        "activity_bonus",
    ]
    COLLAPSIBLE_SINCE_FIELDS_ERRORS = {
        **NewEmployeeRecordStep3Form.COLLAPSIBLE_SINCE_FIELDS_ERRORS,
        "are_allocation": "La durée de l'ARE est obligatoire",
        "activity_bonus": "La durée de la prime d'activité est obligatoire",
    }

    class Meta(NewEmployeeRecordStep3Form.Meta):
        fields = NewEmployeeRecordStep3Form.Meta.fields + [
            "are_allocation_since",
            "activity_bonus_since",
            "cape_freelance",
            "cesa_freelance",
            "actor_met_for_business_creation",
            "mean_monthly_income_before_process",
            "eiti_contributions",
        ]
        help_texts = {
            "cape_freelance": "Contrat d'Appui au Projet Entreprise",
            "cesa_freelance": "Contrat Entrepreneur Salarié Associé",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["actor_met_for_business_creation"].required = True
        self.fields["mean_monthly_income_before_process"].required = True
        self.fields["mean_monthly_income_before_process"].widget.attrs |= {"step": "any"}
        self.fields["eiti_contributions"].required = True


class FinancialAnnexesChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.number} — {obj.start_at:%d/%m/%Y}–{obj.end_at:%d/%m/%Y} — {obj.get_state_display()}"


class NewEmployeeRecordStep4(forms.Form):
    """
    New employee record step 4:

    select a valid financial annex
    """

    financial_annex = FinancialAnnexesChoiceField(
        required=False,
        queryset=None,
        # The Select2Widget adds an empty label when the field is not required.
        empty_label=None,
        label="Annexe financière",
        widget=Select2Widget(),
    )

    def __init__(self, employee_record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.employee_record = employee_record

        convention = employee_record.job_application.to_company.convention
        self.fields["financial_annex"].queryset = convention.financial_annexes.order_by("-end_at", "-number")
        self.fields["financial_annex"].initial = employee_record.financial_annex
        self.fields["financial_annex"].required = False

    def clean(self):
        super().clean()

        self.employee_record.financial_annex = self.cleaned_data["financial_annex"]
