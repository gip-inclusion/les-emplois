from django.contrib import messages

from itou.common_apps.organizations.models import MembershipQuerySet
from itou.gps.models import FollowUpGroup


def add_beneficiary(request, beneficiary):
    added = FollowUpGroup.objects.follow_beneficiary(beneficiary=beneficiary, user=request.user)
    if added:
        messages.success(
            request,
            "Bénéficiaire ajouté||"
            f"{beneficiary.get_full_name()} fait maintenant partie de la liste de vos bénéficiaires.",
            extra_tags="toast",
        )
    else:
        messages.info(
            request,
            "Bénéficiaire déjà dans la liste||"
            f"{beneficiary.get_full_name()} fait déjà partie de la liste de vos bénéficiaires.",
            extra_tags="toast",
        )


def get_all_coworkers(organizations):
    all_active_memberships = MembershipQuerySet.union(*[org.memberships.active() for org in organizations])
    # we cannot pass a union into a filter, but we can first convert it as a subquery to feed it to to_users_qs
    return MembershipQuerySet.to_users_qs(all_active_memberships.values("pk"))
