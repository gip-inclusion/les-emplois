from django.conf import settings
from django.contrib import messages
from django.urls import reverse

from itou.common_apps.organizations.models import MembershipQuerySet
from itou.gps.models import FollowUpGroup
from itou.utils import slack
from itou.utils.templatetags.str_filters import mask_unless
from itou.utils.urls import get_absolute_url


def add_beneficiary(request, beneficiary, notify_duplicate=False, is_active=True):
    membership, added = FollowUpGroup.objects.follow_beneficiary(
        beneficiary=beneficiary, user=request.user, is_active=is_active
    )
    name = mask_unless(
        beneficiary.get_full_name(),
        predicate=membership.can_view_personal_information or request.user.can_view_personal_information(beneficiary),
    )
    if is_active is False:
        messages.info(
            request,
            f"Demande d’ajout envoyée||Votre demande d’ajout pour {name} a bien été transmise pour validation.",
            extra_tags="toast",
        )
    elif added:
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
    if notify_duplicate:
        job_seeker_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(beneficiary.pk,)))
        send_slack_message_for_gps(
            ":black_square_for_stop: Création d’un nouveau bénéficiaire : "
            f"<{job_seeker_admin_url}|{mask_unless(beneficiary.get_full_name(), False)}>."
        )
    return membership


def get_all_coworkers(organizations):
    all_active_memberships = MembershipQuerySet.union(*[org.memberships.active() for org in organizations])
    # we cannot pass a union into a filter, but we can first convert it as a subquery to feed it to to_users_qs
    return MembershipQuerySet.to_users_qs(all_active_memberships.values("pk"))


def send_slack_message_for_gps(text):
    slack.send_slack_message(text, settings.GPS_SLACK_WEBHOOK_URL)
