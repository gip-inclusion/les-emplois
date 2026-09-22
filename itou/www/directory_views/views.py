from datetime import timedelta
from email.utils import formataddr

from django.conf import settings
from django.contrib import messages
from django.core.cache import caches
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from itoutils.urls import add_url_params

from itou.cities.cache import get_directory_active_city_ids
from itou.directory.enums import ContactSubject
from itou.directory.models import ContactMessage
from itou.directory.services import get_directory_person
from itou.utils.auth import check_request
from itou.utils.emails import get_email_message
from itou.utils.readonly import http_methods, readonly_view
from itou.utils.urls import get_safe_url
from itou.www.directory_views.forms import ContactMessageForm


MESSAGE_RATE_LIMIT = 50
MESSAGE_RATE_LIMIT_PERIOD = int(timedelta(days=1).total_seconds())


def can_access_directory(request):
    organization = getattr(request, "current_organization", None)
    return bool(
        request.user.is_professional
        and organization
        and organization.coords
        and organization.insee_city_id in get_directory_active_city_ids()
    )


def _get_person(request, key):
    try:
        person = get_directory_person(request.current_organization.coords, key)
    except ValueError as exc:
        raise Http404 from exc
    if not person:
        raise Http404
    return person


def _person_detail_context(request, person, contact_form=None):
    return {
        "person": person,
        "contact_form": contact_form or ContactMessageForm(),
        "back_url": get_safe_url(
            request,
            "back_url",
            fallback_url=reverse("dashboard:index"),
        ),
        "matomo_custom_title": "Annuaire pro - Fiche personne",
    }


@check_request(can_access_directory)
@readonly_view
def person_detail(request, key, template_name="directory/person_detail.html"):
    return render(request, template_name, _person_detail_context(request, _get_person(request, key)))


@check_request(can_access_directory)
@readonly_view
def reveal_contact(request, key, field):
    person = _get_person(request, key)
    if field not in {"email", "phone"}:
        raise Http404
    org_key = request.GET.get("org")
    if org_key:
        organization = next((item for item in person.organizations if item.key == org_key), None)
        if not organization:
            raise Http404
        value = getattr(organization, field)
        label = "Adresse e-mail de la structure" if field == "email" else "Téléphone de la structure"
    else:
        value = getattr(person, field)
        label = "Adresse e-mail" if field == "email" else "Téléphone"
    if not value:
        raise Http404
    return render(
        request,
        "directory/includes/contact_value.html",
        {"label": label, "value": value},
    )


def _message_rate_limited(user):
    cache = caches["failsafe"]
    cache_key = f"directory-message-throttle-{user.pk}"
    if cache.add(cache_key, 1, timeout=MESSAGE_RATE_LIMIT_PERIOD):
        return False
    return cache.incr(cache_key) > MESSAGE_RATE_LIMIT


@check_request(can_access_directory)
@http_methods(db_write=["POST"])
def send_message(request, key):
    person = _get_person(request, key)
    form = ContactMessageForm(request.POST)
    if form.is_valid():
        if _message_rate_limited(request.user):
            form.add_error(None, "Vous avez atteint la limite de 50 messages envoyés par jour.")
        else:
            subject = form.cleaned_data["subject"]
            custom_subject = form.cleaned_data["custom_subject"]
            subject_label = custom_subject if subject == ContactSubject.OTHER else ContactSubject(subject).label
            ContactMessage.objects.create(
                sender=request.user,
                recipient_id=person.recipient_id,
                subject=subject,
                custom_subject=custom_subject,
            )
            email = get_email_message(
                to=[person.email],
                context={
                    "sender": request.user,
                    "sender_organization": request.current_organization,
                    "subject": subject_label,
                    "body": form.cleaned_data["body"],
                },
                subject="directory/email/contact_message_subject.txt",
                body="directory/email/contact_message_body.txt",
                from_email=formataddr(
                    (f"{request.user.get_full_name()} (via la Plateforme de l’inclusion)", settings.DEFAULT_FROM_EMAIL)
                ),
            )
            email.reply_to = [request.user.email]
            email.send()
            messages.success(request, "Votre message a bien été envoyé.")
            detail_url = reverse("directory:person_detail", kwargs={"key": key})
            return redirect(add_url_params(detail_url, {"back_url": request.POST.get("back_url", "")}))
    return render(request, "directory/person_detail.html", _person_detail_context(request, person, form))
