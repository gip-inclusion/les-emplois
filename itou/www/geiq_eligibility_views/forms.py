from django import forms

from itou.companies.enums import SiaeKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria


class GEIQAdministrativeCriteriaForm(forms.Form):
    # Mainly for authorized prescribers

    RADIO_FIELDS = [
        "de_inscrit_depuis_moins_de_12_mois",
        "deld_12_24_mois",
        "detld_24_mois",
    ]

    # If 'key' field is checked, disable fields in 'value' list
    EXCLUSIONS = {
        "resident_qpv": ("resident_zrr",),
        "resident_zrr": ("resident_qpv",),
        "jeune_26_ans": ("senior_50_ans", "de_45_ans_et_plus"),
        "senior_50_ans": ("jeune_26_ans", "sortant_ase"),
        "de_45_ans_et_plus": ("jeune_26_ans", "sortant_ase"),
        "sortant_ase": ("senior_50_ans", "de_45_ans_et_plus"),
        "refugie_statutaire": ("demandeur_asile",),
        "demandeur_asile": ("refugie_statutaire",),
    }

    # Foldable optional radio fields
    pole_emploi_related = forms.CharField(max_length=100, required=False)

    def __init__(self, siae, administrative_criteria, form_url, accept_no_criteria=True, **kwargs):
        if not siae or siae.kind != SiaeKind.GEIQ:
            raise ValueError("This form is only for GEIQ")

        if administrative_criteria is None:
            raise ValueError("This form needs a list of criteria, even empty")

        if not form_url:
            raise ValueError("This form needs a submit URL")

        super().__init__(**kwargs)

        self.siae = siae
        self.accept_no_criteria = accept_no_criteria
        self.criteria = list(GEIQAdministrativeCriteria.objects.all().order_by("ui_rank"))
        selected_pks = [ac.pk for ac in administrative_criteria]

        # Process most of the fields as checkboxes
        for criterion in self.criteria:
            # Exclude pseudo-radio fields (more below):
            if criterion.key in self.RADIO_FIELDS:
                continue

            self.fields[criterion.key] = forms.BooleanField(
                required=False,
                label=criterion.name,
                help_text=criterion.desc,
                initial=criterion.pk in selected_pks,
            )

            # Every criterion has the ability to reload the form via HTMX on value changed
            # `hx-post` is not inherited
            # see: https://htmx.org/docs/#parameters
            self.fields[criterion.key].widget.attrs.update(
                {"hx-trigger": "change", "hx-post": form_url, "class": "form-check-input"}
            )

            # Displayed for GEIQ, not for prescribers
            if not accept_no_criteria and criterion.written_proof:
                self.fields[criterion.key].help_text += (
                    f"<p class='mt-2 form-text text-muted fs-xs'><strong>Pièce justificative :</strong> "
                    f"{criterion.written_proof}</p>"
                )

        # Setting-up conditional radio field for PE duration
        radio_choices = [
            (c.pk, c.name)
            for c in self.criteria
            if c.slug in ("de-inscrit-depuis-moins-de-12-mois", "deld-12-24-mois", "detld-24-mois")
        ]
        self.fields["pole_emploi_related"].widget = forms.RadioSelect(choices=radio_choices)
        self.fields["pole_emploi_related"].widget.attrs.update({"hx-trigger": "change", "hx-post": form_url})

        for pk, _ in radio_choices:
            if pk in selected_pks:
                # Casting needed, or has_changed fails
                self.initial.setdefault("pole_emploi_related", str(pk))
                break

    def _get_administrative_criteria(self):
        # Get a list of GEIQ administrative criteria from form data
        if self.cleaned_data:
            selected_criteria = []
            for criterion in self.criteria:
                # Exclude checked children without parent
                if criterion.parent and not self.cleaned_data.get(criterion.parent.key):
                    continue
                # Normal case
                if self.cleaned_data.get(criterion.key):
                    selected_criteria.append(criterion)
                # Optional radio element (uses pk as value)
                if pk := self.cleaned_data.get("pole_emploi_related"):
                    if int(pk) == criterion.pk:
                        selected_criteria.append(criterion)
            return selected_criteria

    def _handle_exclusions(self):
        for key, fields_to_disable in self.EXCLUSIONS.items():
            if self.cleaned_data[key]:
                for field_key in fields_to_disable:
                    self.fields[field_key].disabled = True
                    self.fields[field_key].widget.attrs.update({"class": "bg-light"})

    def clean(self):
        cleaned_data = super().clean()

        self._handle_exclusions()

        # Can't be senior and youngster
        if (cleaned_data.get("senior_50_ans") or cleaned_data.get("de_45_ans_et_plus")) and cleaned_data.get(
            "jeune_26_ans"
        ):
            raise forms.ValidationError("Incohérence dans les critères d'âge")

        # Can't be senior and out of ASE
        if (cleaned_data.get("senior_50_ans") or cleaned_data.get("de_45_ans_et_plus")) and cleaned_data.get(
            "sortant_ase"
        ):
            raise forms.ValidationError("Incohérence dans les critères d'âge par rapport à l'ASE")

        if cleaned_data.get("refugie_statutaire") and cleaned_data.get("demandeur_asile"):
            raise forms.ValidationError(
                """Attention le cumul des  critères """
                """"Réfugiés statutaire ou bénéficiaire de la protection subsidiaire" """
                """et "Demandeur d’asile" n’est pas possible"""
            )

        if cleaned_data.get("resident_qpv") and cleaned_data.get("resident_zrr"):
            raise forms.ValidationError("Le cumul des critères QPV et ZRR n’est pas possible")

        criteria = self._get_administrative_criteria()

        if not self.accept_no_criteria and not criteria:
            # Only for GEIQ, not for authorized prescribers
            raise forms.ValidationError("Vous devez saisir au moins un critère d'éligibilité GEIQ")

        return criteria


class GEIQAdministrativeCriteriaForGEIQForm(GEIQAdministrativeCriteriaForm):
    # Specific for .. GEIQ structure (not prescriber)
    proof_of_eligibility = forms.BooleanField(required=False)

    def __init__(self, siae, administrative_criteria, form_url, **kwargs):
        super().__init__(siae, administrative_criteria, form_url, accept_no_criteria=False, **kwargs)

        proof_of_eligibility = self.fields["proof_of_eligibility"]
        proof_of_eligibility.widget.attrs.update({"hx-trigger": "change", "hx-post": form_url})
        proof_of_eligibility.label = (
            "Si le candidat est éligible à l’aide à l’accompagnement GEIQ, "
            "je m'engage à conserver les justificatifs correspondants aux critères "
            "d'éligibilité sélectionnés pour 24 mois, en cas de contrôle."
        )
