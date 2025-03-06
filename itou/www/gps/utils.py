from django.conf import settings
from django.contrib import messages
from django.urls import reverse

from itou.common_apps.organizations.models import MembershipQuerySet
from itou.gps.models import FollowUpGroup
from itou.utils import slack


def add_beneficiary(request, beneficiary, notify_duplicate=False):
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
    if notify_duplicate:
        job_seeker_admin_url = reverse("admin:users_user_change", args=(beneficiary.pk,))
        send_slack_message_for_gps(
            ":black_square_for_stop: Création d’un nouveau bénéficiaire : "
            f'<a href="{job_seeker_admin_url}">{beneficiary.get_full_name()}</a>.'
        )


def get_all_coworkers(organizations):
    all_active_memberships = MembershipQuerySet.union(*[org.memberships.active() for org in organizations])
    # we cannot pass a union into a filter, but we can first convert it as a subquery to feed it to to_users_qs
    return MembershipQuerySet.to_users_qs(all_active_memberships.values("pk"))


def send_slack_message_for_gps(text):
    slack.send_slack_message(text, settings.GPS_SLACK_WEBHOOK_URL)
