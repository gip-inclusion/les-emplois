from django.conf import settings
from django.contrib import messages

from itou.common_apps.organizations.models import MembershipQuerySet
from itou.gps.models import FollowUpGroup
from itou.utils import slack
from itou.utils.templatetags.str_filters import mask_unless


def add_beneficiary(request, beneficiary):
    added = FollowUpGroup.objects.follow_beneficiary(beneficiary=beneficiary, user=request.user)
    name = mask_unless(beneficiary.get_full_name(), predicate=request.user.can_view_personal_information(beneficiary))
    if added:
        messages.success(
            request,
            f"Bénéficiaire ajouté||{name} fait maintenant partie de la liste de vos bénéficiaires.",
            extra_tags="toast",
        )
    else:
        messages.info(
            request,
            f"Bénéficiaire déjà dans la liste||{name} fait déjà partie de la liste de vos bénéficiaires.",
            extra_tags="toast",
        )


def get_all_collegues(organizations):
    all_active_memberships = MembershipQuerySet.union(*[org.memberships.active() for org in organizations])
    # we cannot pass a union into a filter, but we can first convert it as a subquery to feed it to to_users_qs
    return MembershipQuerySet.to_users_qs(all_active_memberships.values("pk"))


def send_slack_message_for_gps(text):
    slack.send_slack_message(text, settings.GPS_SLACK_WEBHOOK_URL)
