from django import forms
from django.db.models.fields import BLANK_CHOICE_DASH
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.text import format_lazy

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, department_from_postcode
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company, CompanyMembership, JobDescription
from itou.jobs.models import Appellation
from itou.utils import constants as global_constants
from itou.utils.urls import get_external_link_markup
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class CreateCompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "siret",
            "kind",
            "name",
            "brand",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
            "phone",
            "email",
            "website",
            "description",
        ]
        help_texts = {
            "siret": ("Saisissez 14 chiffres. Doit être un SIRET avec le même SIREN que votre structure actuelle."),
            "kind": "Votre nouvelle structure doit avoir le même type que votre structure actuelle.",
            "brand": "Si ce champ est renseigné, il sera utilisé en tant que nom sur la fiche.",
            "website": "Votre site web doit commencer par http:// ou https://",
            "description": "Texte de présentation de votre structure.",
        }

    def __init__(self, current_company, current_user, *args, **kwargs):
        self.current_company = current_company
        self.current_user = current_user
        super().__init__(*args, **kwargs)

        self.fields["kind"].choices = [(current_company.kind, dict(CompanyKind.choices)[current_company.kind])]

        self.fields["department"].choices = [("", "---")] + list(DEPARTMENTS.items())

        required_fields = ["address_line_1", "post_code", "city", "department", "phone"]
        for required_field in required_fields:
            self.fields[required_field].required = True

    def clean_kind(self):
        return self.current_company.kind

    def clean(self):
        siret = self.cleaned_data.get("siret")
        kind = self.cleaned_data.get("kind")
        existing_siae_query = Company.objects.filter(siret=siret, kind=kind)

        if existing_siae_query.exists():
            error_message = """
                La structure à laquelle vous souhaitez vous rattacher est déjà
                connue de nos services. Merci de nous contacter à l'adresse
                """
            external_link = get_external_link_markup(
                url=global_constants.ITOU_HELP_CENTER_URL,
                text=global_constants.ITOU_HELP_CENTER_URL,
            )
            error_message_siret = (
                "en précisant votre numéro de SIRET (si existant),"
                " le type et l’adresse de cette structure, ainsi que votre numéro de téléphone"
                " pour être contacté(e) si nécessaire."
            )
            error_message = mark_safe(f"{error_message} {external_link} {error_message_siret}")
            raise forms.ValidationError(error_message)

        if not siret.startswith(self.current_company.siren):
            raise forms.ValidationError(f"Le SIRET doit commencer par le SIREN {self.current_company.siren}")

        return self.cleaned_data

    def save(self, commit=False):
        company = super().save(commit=False)
        company.set_coords()
        company.created_by = self.current_user
        company.source = Company.SOURCE_USER_CREATED
        company.convention = self.current_company.convention
        company.save()

        CompanyMembership.objects.create(company=company, is_admin=True, user=self.current_user)

        return company


class EditCompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "brand",
            "address_line_1",
            "address_line_2",
            "post_code",
            "department",  # will not be displayed in the template but filled with clean_department
            "city",
            "phone",
            "email",
            "website",
        ]
        labels = {
            "brand": "Nom à afficher",
            "post_code": "Code postal",
            "city": "Ville",
            "email": "Email",
        }
        help_texts = {
            "brand": "Nom présent sur la fiche et dans les résultats de recherche.",
            "description": "Texte de présentation de votre structure.",
            "address_line_1": "Appartement, suite, bloc, bâtiment, boite postale, etc.",
            "address_line_2": "",
            "website": "Votre site web doit commencer par http:// ou https://",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        required_fields = ["brand", "address_line_1", "post_code", "city", "phone", "email"]
        for required_field in required_fields:
            self.fields[required_field].required = True

        self.fields["brand"].widget.attrs["placeholder"] = ""
        self.fields["address_line_1"].widget.attrs["placeholder"] = ""
        self.fields["address_line_2"].widget.attrs["placeholder"] = ""

    def clean_department(self):
        post_code = self.cleaned_data.get("post_code")
        return department_from_postcode(post_code)


class EditSiaeDescriptionForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "description",
            "provided_support",
        ]
        labels = {
            "description": "Description générale de l'activité",
            "provided_support": "Type d'accompagnement proposé",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].widget.attrs[
            "placeholder"
        ] = "Présentez votre entreprise, votre secteur d’activité, domaines d’intervention, etc."
        self.fields["provided_support"].widget.attrs[
            "placeholder"
        ] = "Indiquez les modalités d’accompagnement, par qui, comment, à quelle fréquence, etc."


class BlockJobApplicationsForm(forms.ModelForm):
    """
    Toggle blocking new job applications for this SIAE (used in dashboard settings)
    """

    class Meta:
        model = Company
        fields = ["block_job_applications"]
        labels = {
            "block_job_applications": "Bloquer temporairement la réception de candidatures "
            "(candidatures spontanées, recrutements)"
        }

    def save(self, commit=True):
        company = super().save(commit=commit)
        block_job_applications = self.cleaned_data["block_job_applications"]

        if commit:
            if block_job_applications:
                company.job_applications_blocked_at = timezone.now()
            company.block_job_applications = block_job_applications
            company.save()
        return company


class FinancialAnnexSelectForm(forms.Form):
    """
    Select a financial annex matching the same SIREN and kind as the convention of the current siae.
    """

    def __init__(self, *args, **kwargs):
        self.financial_annexes = kwargs.pop("financial_annexes")
        super().__init__(*args, **kwargs)
        self.fields["financial_annexes"].queryset = self.financial_annexes
        self.fields["financial_annexes"].label_from_instance = self.label_from_instance

    @staticmethod
    def label_from_instance(siae):
        """
        Display a custom value for the AF in the dropdown instead of the default af.__str__.

        From https://stackoverflow.com/questions/41969899/display-field-other-than-str
        """
        return siae.number_prefix_with_spaces

    financial_annexes = forms.ModelChoiceField(
        label="Numéro d'annexe financière sans son suffixe de type 'A1M1'",
        queryset=None,
        widget=forms.Select,
        help_text="Veuillez sélectionner un numéro existant.",
    )


# SIAE job descriptions forms (2 steps and session based)


class JobAppellationAndLocationMixin(forms.Form):
    # NB we need to inherit from forms.Form if we want the attributes
    # to be added to the a Form using this mixin (django magic)

    appellation = forms.ModelChoiceField(
        queryset=Appellation.objects,
        label="Poste (code ROME)",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": format_lazy("{}?select2=", reverse_lazy("autocomplete:jobs")),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 2,
                "data-placeholder": "Ex. K2204 ou agent/agente d'entretien en crèche.",
            },
        ),
        required=False,
    )

    location = forms.ModelChoiceField(
        queryset=City.objects,
        label="Localisation du poste (si différente du siège)",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": format_lazy("{}?select2=", reverse_lazy("autocomplete:cities")),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 2,
                "data-placeholder": "Ex. Poitiers",
            },
        ),
        required=False,
    )

    class Meta:
        model = JobDescription
        fields = [
            "appellation",
            "custom_name",
            "location",
            "market_context_description",
            "contract_type",
            "other_contract_type",
            "hours_per_week",
            "open_positions",
        ]
        labels = {
            "custom_name": "Nom du poste à afficher",
            "hours_per_week": "Nombre d'heures par semaine",
            "open_positions": "Nombre de poste(s) ouvert(s) au recrutement",
        }
        help_texts = {
            "custom_name": "Si le champ est renseigné, il sera utilisé à la place du nom ci-dessus.",
            "other_contract_type": "Veuillez préciser quel est le type de contrat.",
        }


# Job descriptions forms (2 steps and session based)
class EditJobDescriptionForm(JobAppellationAndLocationMixin, forms.ModelForm):
    def __init__(self, current_company: Company, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["appellation"].required = True

        if self.instance.pk and self.instance.contract_type != ContractType.OTHER:
            self.fields["other_contract_type"].widget.attrs.update({"disabled": "disabled"})

        self.fields["custom_name"].widget.attrs.update({"placeholder": ""})
        self.fields["hours_per_week"].widget.attrs.update({"placeholder": ""})
        self.fields["other_contract_type"].widget.attrs.update({"placeholder": ""})
        self.fields["market_context_description"].widget.attrs.update(
            {"placeholder": "Décrire en quelques mots l'objet du marché."}
        )

        self.fields["contract_type"].required = True
        self.fields["open_positions"].required = True

        if current_company.is_opcs:
            self.fields["market_context_description"].required = True
        else:
            del self.fields["market_context_description"]

        self.fields["contract_type"].choices = BLANK_CHOICE_DASH + ContractType.choices_for_company(
            company=current_company
        )

    class Meta:
        model = JobDescription
        fields = [
            "appellation",
            "custom_name",
            "location",
            "market_context_description",
            "contract_type",
            "other_contract_type",
            "hours_per_week",
            "open_positions",
        ]
        labels = {
            "custom_name": "Nom du poste à afficher",
            "hours_per_week": "Nombre d'heures par semaine",
            "open_positions": "Nombre de poste(s) ouvert(s) au recrutement",
        }
        help_texts = {
            "custom_name": "Si le champ est renseigné, il sera utilisé à la place du nom ci-dessus.",
            "other_contract_type": "Veuillez préciser quel est le type de contrat.",
        }

    def clean_open_positions(self):
        open_positions = self.cleaned_data.get("open_positions")
        if open_positions is not None and open_positions < 1:
            raise forms.ValidationError("Il doit y avoir au moins un poste ouvert.")
        return open_positions


class EditJobDescriptionDetailsForm(forms.ModelForm):
    class Meta:
        model = JobDescription
        fields = [
            "description",
            "profile_description",
            "is_resume_mandatory",
            "is_qpv_mandatory",
        ]
        labels = {
            "description": "Les missions",
            "profile_description": "Profil recherché et prérequis",
            "is_resume_mandatory": "Le CV est nécessaire pour le traitement de la candidature",
            "is_qpv_mandatory": "Le marché s’inscrit dans le cadre du NPNRU et ces clauses sociales doivent "
            "bénéficier en priorité aux publics résidant en Quartier Prioritaire de la Ville.",
        }

    def __init__(self, current_company: Company, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholder = "Soyez le plus concret possible"
        self.fields["description"].widget.attrs.update({"placeholder": placeholder})
        self.fields["profile_description"].widget.attrs.update({"placeholder": placeholder})

        if not current_company.is_opcs:
            del self.fields["is_qpv_mandatory"]
