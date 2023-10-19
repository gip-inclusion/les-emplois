from django import forms
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.safestring import mark_safe

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, department_from_postcode
from itou.companies.enums import ContractType, SiaeKind
from itou.companies.models import Siae, SiaeJobDescription, SiaeMembership
from itou.jobs.models import Appellation
from itou.utils import constants as global_constants
from itou.utils.urls import get_external_link_markup


class CreateSiaeForm(forms.ModelForm):
    class Meta:
        model = Siae
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

    def __init__(self, current_siae, current_user, *args, **kwargs):
        self.current_siae = current_siae
        self.current_user = current_user
        super().__init__(*args, **kwargs)

        self.fields["kind"].choices = [(current_siae.kind, dict(SiaeKind.choices)[current_siae.kind])]

        self.fields["department"].choices = [("", "---")] + list(DEPARTMENTS.items())

        required_fields = ["address_line_1", "post_code", "city", "department", "phone"]
        for required_field in required_fields:
            self.fields[required_field].required = True

    def clean_kind(self):
        return self.current_siae.kind

    def clean(self):
        siret = self.cleaned_data.get("siret")
        kind = self.cleaned_data.get("kind")
        existing_siae_query = Siae.objects.filter(siret=siret, kind=kind)

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

        if not siret.startswith(self.current_siae.siren):
            raise forms.ValidationError(f"Le SIRET doit commencer par le SIREN {self.current_siae.siren}")

        return self.cleaned_data

    def save(self, commit=False):
        siae = super().save(commit=False)
        siae.set_coords(siae.geocoding_address, post_code=siae.post_code)
        siae.created_by = self.current_user
        siae.source = Siae.SOURCE_USER_CREATED
        siae.convention = self.current_siae.convention
        siae.save()

        SiaeMembership.objects.create(siae=siae, is_admin=True, user=self.current_user)

        return siae


class EditSiaeForm(forms.ModelForm):
    class Meta:
        model = Siae
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
        model = Siae
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
        model = Siae
        fields = ["block_job_applications"]
        labels = {
            "block_job_applications": "Bloquer temporairement la réception de candidatures "
            "(candidatures spontanées, recrutements)"
        }

    def save(self, commit=True):
        siae = super().save(commit=commit)
        block_job_applications = self.cleaned_data["block_job_applications"]

        if commit:
            if block_job_applications:
                siae.job_applications_blocked_at = timezone.now()
            siae.block_job_applications = block_job_applications
            siae.save()
        return siae


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


class EditJobDescriptionForm(forms.ModelForm):
    JOBS_AUTOCOMPLETE_URL = reverse_lazy("autocomplete:jobs")

    # See: itou/static/js/job_autocomplete.js
    job_appellation = forms.CharField(
        label="Poste (code ROME)",
        widget=forms.TextInput(
            attrs={
                "class": "js-job-autocomplete-input form-control",
                "data-autosubmit-on-enter-pressed": 0,
                "placeholder": "Ex. K2204 ou agent/agente d'entretien en crèche.",
                "autocomplete": "off",
            }
        ),
    )
    # Hidden placeholder field for "real" job appellation.
    job_appellation_code = forms.CharField(
        max_length=6, widget=forms.HiddenInput(attrs={"class": "js-job-autocomplete-hidden form-control"})
    )

    LOCATION_AUTOCOMPLETE_URL = reverse_lazy("autocomplete:cities")
    location_label = forms.CharField(
        label="Localisation du poste (si différent du siège)",
        widget=forms.TextInput(
            attrs={
                "class": "js-city-autocomplete-input form-control",
                "data-autosubmit-on-enter-pressed": 0,
                "data-autocomplete-source-url": LOCATION_AUTOCOMPLETE_URL,
                "placeholder": "Ex. Poitiers",
                "autocomplete": "off",
            }
        ),
        required=False,
    )

    location_code = forms.CharField(
        required=False, widget=forms.HiddenInput(attrs={"class": "js-city-autocomplete-hidden"})
    )

    class Meta:
        model = SiaeJobDescription
        fields = [
            "job_appellation",
            "job_appellation_code",
            "custom_name",
            "location_label",
            "location_code",
            "market_context_description",
            "contract_type",
            "other_contract_type",
            "hours_per_week",
            "open_positions",
        ]
        labels = {
            "custom_name": "Nom du poste à afficher",
            "location_label": "Localisation du poste (si différente du siège)",
            "hours_per_week": "Nombre d'heures par semaine",
            "open_positions": "Nombre de poste(s) ouvert(s) au recrutement",
        }
        help_texts = {
            "custom_name": "Si le champ est renseigné, il sera utilisé à la place du nom ci-dessus.",
            "other_contract_type": "Veuillez préciser quel est le type de contrat.",
        }

    def __init__(self, current_siae: Siae, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.siae = current_siae

        if self.instance.pk:
            self.fields["job_appellation"].initial = self.instance.appellation.name
            self.fields["job_appellation_code"].initial = self.instance.appellation.code

            if self.instance.location:
                # Optional field
                self.fields["location_label"].initial = self.instance.location.name
                self.fields["location_code"].initial = self.instance.location.slug

            if self.instance.contract_type != ContractType.OTHER:
                self.fields["other_contract_type"].widget.attrs.update({"disabled": "disabled"})

        # Pass SIAE id in autocomplete call
        self.fields["job_appellation"].widget.attrs.update(
            {
                "data-autocomplete-source-url": self.JOBS_AUTOCOMPLETE_URL + f"?siae_id={current_siae.pk}",
            }
        )

        self.fields["custom_name"].widget.attrs.update({"placeholder": ""})
        self.fields["hours_per_week"].widget.attrs.update({"placeholder": ""})
        self.fields["other_contract_type"].widget.attrs.update({"placeholder": ""})
        self.fields["market_context_description"].widget.attrs.update(
            {"placeholder": "Décrire en quelques mots l'objet du marché."}
        )

        self.fields["contract_type"].required = True
        self.fields["open_positions"].required = True
        self.fields["job_appellation_code"].required = False
        self.fields["job_appellation"].required = True

        if current_siae.is_opcs:
            self.fields["market_context_description"].required = True
        else:
            del self.fields["market_context_description"]

        self.fields["contract_type"].choices = [
            (
                "",
                "---------",
            )
        ] + ContractType.choices_for_siae(siae=current_siae)

    def clean_job_appellation_code(self):
        job_appellation_code = self.cleaned_data.get("job_appellation_code")
        if not job_appellation_code:
            raise forms.ValidationError("Le poste n'est pas correctement renseigné.")
        return int(job_appellation_code)

    def clean_open_positions(self):
        open_positions = self.cleaned_data.get("open_positions")
        if open_positions is not None and open_positions < 1:
            raise forms.ValidationError("Il doit y avoir au moins un poste ouvert.")
        return open_positions

    def clean(self):
        # Bind `Appellation` and `City` objects
        appellation_code = self.cleaned_data.get("job_appellation_code")
        if appellation_code:
            self.instance.appellation = Appellation.objects.get(code=appellation_code)

        location_code = self.cleaned_data.get("location_code")
        if location_code:
            self.instance.location = City.objects.get(slug=location_code)


class EditJobDescriptionDetailsForm(forms.ModelForm):
    class Meta:
        model = SiaeJobDescription
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

    def __init__(self, current_siae: Siae, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.siae = current_siae

        placeholder = "Soyez le plus concret possible"
        self.fields["description"].widget.attrs.update({"placeholder": placeholder})
        self.fields["profile_description"].widget.attrs.update({"placeholder": placeholder})

        if not current_siae.is_opcs:
            del self.fields["is_qpv_mandatory"]
