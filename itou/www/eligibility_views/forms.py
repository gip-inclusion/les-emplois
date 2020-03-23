from django import forms
from django.utils.translation import gettext as _, gettext_lazy

from itou.eligibility.models import AdministrativeCriteriaLevel1, AdministrativeCriteriaLevel2


class ConfirmEligibilityForm(forms.Form):

    confirm = forms.BooleanField(
        label=gettext_lazy(
            "Je confirme que le candidat remplit les critères d'éligibilité à l'IAE et "
            "m'engage à fournir les justificatifs correspondants en cas de contrôle a posteriori."
        )
    )

    def clean_confirm(self):
        if not self.cleaned_data["confirm"]:
            error = _("Vous devez confirmer l'éligibilité du candidat.")
            raise forms.ValidationError(error)


class AdministrativeCriteriaLevel1Form(forms.ModelForm):
    class Meta:
        model = AdministrativeCriteriaLevel1
        fields = ["is_beneficiaire_du_rsa", "is_allocataire_ass", "is_allocataire_aah", "is_detld_24_mois"]


class AdministrativeCriteriaLevel2Form(forms.ModelForm):
    class Meta:
        model = AdministrativeCriteriaLevel2
        fields = [
            "is_niveau_detude_3_infra",
            "is_senior_50_ans",
            "is_jeune_26_ans",
            "is_sortant_de_lase",
            "is_deld",
            "is_travailleur_handicape",
            "is_parent_isole",
            "is_sans_hebergement",
            "is_primo_arrivant",
            "is_resident_zrr",
            "is_resident_qpv",
        ]
