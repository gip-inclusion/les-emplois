from itou.users.models import User
from itou.www.insertion_views.forms import OrientationsFilterForm


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
