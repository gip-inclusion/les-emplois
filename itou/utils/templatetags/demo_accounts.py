import logging

from django import template
from django.urls import reverse


logger = logging.getLogger(__name__)
register = template.Library()


@register.simple_tag
def admin_accounts_tag():
    action_url = reverse("login:demo")
    return [
        {
            "title": "Admin",
            "email": "admin@test.com",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def employers_accounts_tag():
    action_url = reverse("login:demo")
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
            "title": "AI",
            "email": "demo.emplois+ai@inclusion.gouv.fr",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def prescribers_accounts_tag():
    action_url = reverse("login:demo")
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
    ]


@register.simple_tag
def job_seekers_accounts_tag():
    user_email = "demo.emplois+de@inclusion.gouv.fr"
    action_url = reverse("login:demo")
    return [{"title": "Candidat", "email": user_email, "action_url": action_url}]
