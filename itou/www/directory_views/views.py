from datetime import timedelta
from email.utils import formataddr

from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from itoutils.urls import add_url_params

from itou.api.throttling import FailSafeUserRateThrottle
from itou.directory.enums import ContactSubject
from itou.directory.models import ContactMessage
from itou.directory.services import get_directory_people, get_directory_person
from itou.emails.utils import get_email_message
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import http_methods, readonly_view
from itou.utils.urls import get_safe_url
from itou.www.directory_views.forms import ContactMessageForm, PeopleSearchForm
from itou.www.directory_views.perms import can_access_directory


MESSAGE_RATE_LIMIT = 50
MESSAGE_RATE_LIMIT_PERIOD = int(timedelta(days=1).total_seconds())


def _filter_people(people, form):
    selected_person_key = form.cleaned_data["q"]
    structure_types = set(form.cleaned_data["types"])
    if selected_person_key:
        people = [person for person in people if person.public_id == selected_person_key]
    if structure_types:
        # Match any affiliation, even if another structure is shown first.
        people = [
            person
            for person in people
            if structure_types.intersection(organization.kind for organization in person.organizations)
        ]
    return people


@check_request(can_access_directory)
@readonly_view
def people_results(request, template_name="directory/people_results.html"):
    people = get_directory_people(request.current_organization.coords)
    form = PeopleSearchForm(request.GET, people=people)
    if form.is_valid():
        people = _filter_people(people, form)
    else:
        people = []
    results = pager(people, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)
    context = {
        "form": form,
        "results": results,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(
        request,
        "directory/includes/people_results.html" if request.htmx else template_name,
        context,
    )


def _get_person(request, public_id):
    person = get_directory_person(request.current_organization.coords, public_id)
    if not person:
        raise Http404
    return person


def _person_detail_context(request, person, contact_form=None):
    throttle = MessageThrottle()
    return {
        "person": person,
        "contact_form": contact_form or ContactMessageForm(),
        "rate_limited_message": throttle.limit_message if throttle.is_throttled(request, None) else None,
        "back_url": get_safe_url(
            request,
            "back_url",
            fallback_url=reverse("directory:people_results"),
        ),
        "matomo_custom_title": "Annuaire pro - Fiche personne",
    }


@check_request(can_access_directory)
@readonly_view
def person_detail(request, public_id, template_name="directory/person_detail.html"):
    return render(request, template_name, _person_detail_context(request, _get_person(request, public_id)))


class MessageThrottle(FailSafeUserRateThrottle):
    scope = "directory-message-user"
    rate = "50/day"

    @property
    def limit_message(self):
        return f"Vous avez atteint la limite de messages envoyés : {self.french_rate_limit(self.rate)}."


@check_request(can_access_directory)
@http_methods(db_write=["POST"])
def send_message(request, public_id):
    person = _get_person(request, public_id)
    form = ContactMessageForm(request.POST)
    if form.is_valid():
        throttle = MessageThrottle()
        if not throttle.allow_request(request, None):
            form.add_error(None, throttle.limit_message)
        else:
            subject = form.cleaned_data["subject"]
            custom_subject = form.cleaned_data["custom_subject"]
            subject_label = custom_subject if subject == ContactSubject.OTHER else ContactSubject(subject).label
            # Save the contact event, but keep the message body only in the outgoing email.
            ContactMessage.objects.create(
                sender=request.user,
                recipient_id=person.public_id,
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
                body="directory/email/contact_message_body.md",
                from_email=formataddr(
                    (f"{request.user.get_full_name()} (via la Plateforme de l’inclusion)", settings.DEFAULT_FROM_EMAIL)
                ),
                reply_to=[request.user.email],
            )
            email.send()
            messages.success(request, "Votre message a bien été envoyé.")
            detail_url = reverse("directory:person_detail", kwargs={"public_id": public_id})
            return redirect(add_url_params(detail_url, {"back_url": get_safe_url(request, "back_url")}))
    return render(request, "directory/person_detail.html", _person_detail_context(request, person, form))
