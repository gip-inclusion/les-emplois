from itou.companies.enums import ProSupportReportSolution
from itou.inclusion_pass.models import BilanIntervention
from itou.users.models import User
from itou.www.insertion_views.forms import OrientationsFilterForm
from itou.www.job_seekers_views.forms import ProSupportReportForm


class DemandesRecuesFilterForm(OrientationsFilterForm):
    """Filters of the orientations received by an offreur.

    The receiving structure sees the people oriented to it, and the senders belong to other organizations.
    """

    def _get_choices_for_beneficiary(self, orientations_qs, request):
        beneficiaries = User.objects.filter(pk__in=orientations_qs.values("beneficiary")).order_by(
            "last_name", "first_name"
        )
        return [(user.pk, name) for user in beneficiaries if (name := user.get_inverted_full_name())]

    def _get_choices_for_senders(self, orientations_qs, request_organization):
        senders = User.objects.filter(pk__in=orientations_qs.values("sender"))
        return sorted(((user.pk, name) for user in senders if (name := user.get_full_name())), key=lambda c: c[1])


class BilanInterventionForm(ProSupportReportForm):
    """The SIAE pro support report, worded for a person followed by an offreur."""

    class Meta(ProSupportReportForm.Meta):
        model = BilanIntervention

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["barriers"].label = "L’usager a-t-il des freins périphériques identifiés\u202f?"
        self.fields["autonomy"].label = "Cet usager est-il autonome dans ses démarches de recherche d’emploi\u202f?"
        self.fields[
            "has_solution"
        ].label = "Une solution est-elle déjà prévue pour l’usager après l’accompagnement\u202f?"
        self.fields["has_solution"].help_text = (
            "Il s’agit de la suite du parcours une fois l’accompagnement terminé\xa0: emploi, formation… "
            "Répondez «\xa0Non\xa0» si rien n’est encore prévu."
        )
        # A contract renewal only makes sense in a SIAE
        self.fields["solution"].choices = [
            choice for choice in self.fields["solution"].choices if choice[0] != ProSupportReportSolution.RENEWAL
        ]
