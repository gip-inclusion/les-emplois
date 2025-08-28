import logging

from django import template
from django.urls import reverse

from itou.users.enums import UserKind
from itou.users.models import User


logger = logging.getLogger(__name__)
register = template.Library()


@register.simple_tag
def admin_accounts_tag():
    action_url = reverse("login:itou_staff")
    return [
        {
            "title": "Admin",
            "email": "admin@test.com",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def employers_accounts_tag():
    action_url = reverse("login:employer")
    return [
        {
            "title": "ETTI",
            "email": "demo.emplois+etti@inclusion.gouv.fr",
            "action_url": action_url,
        },
        {
            "title": "EI",
            "email": "demo.emplois+ei@inclusion.gouv.fr",
            "action_url": action_url,
        },
        {
            "title": "GEIQ",
            "email": "demo.emplois+geiq@inclusion.gouv.fr",
            "action_url": action_url,
        },
        {
            "title": "EA",
            "email": "demo.emplois+ea@inclusion.gouv.fr",
            "action_url": action_url,
        },
        {
            "title": "AI",
            "email": "demo.emplois+ai@inclusion.gouv.fr",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def prescribers_accounts_tag():
    action_url = reverse("login:prescriber")
    return [
        {
            "title": "Prescripteur habilité",
            "email": "demo.emplois+prescripteur@inclusion.gouv.fr",
            "action_url": action_url,
        },
        {
            "title": "Orienteur",
            "email": "demo.emplois+orienteur@inclusion.gouv.fr",
            "action_url": action_url,
        },
        {
            "title": "Orienteur seul sans organisation",
            "email": "demo.emplois+orienteur-solo@inclusion.gouv.fr",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def job_seekers_accounts_tag():
    user_email = "demo.emplois+de@inclusion.gouv.fr"
    try:
        user_public_id = User.objects.get(kind=UserKind.JOB_SEEKER, email=user_email).public_id
    except User.DoesNotExist:
        logger.warning(
            f"Unable to initialise job_seekers_accounts_tag: no job seeker with email='{user_email}' found !"
        )
        return []  # Fail.

    action_url = reverse("login:existing_user", kwargs={"user_public_id": user_public_id})
    return [{"title": "Candidat", "email": user_email, "action_url": action_url}]
