from email.header import decode_header, make_header

from django.core.cache import caches
from django.urls import reverse
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertRedirects

from itou.directory.enums import ContactSubject
from itou.directory.models import ContactMessage
from tests.www.directory_views.helpers import get_target_person


def test_send_message_persists_subject_only(client, mailoutbox):
    sender, _, _, person = get_target_person(client)
    key = person.key
    url = reverse("directory:send_message", kwargs={"key": key})
    back_url = reverse("dashboard:index")

    response = client.post(
        url,
        {
            "subject": ContactSubject.OTHER,
            "custom_subject": "Échange de pratiques",
            "body": "Ce contenu ne doit pas être enregistré.",
            "back_url": back_url,
        },
    )

    assertRedirects(
        response,
        add_url_params(reverse("directory:person_detail", kwargs={"key": key}), {"back_url": back_url}),
        fetch_redirect_response=False,
    )
    [message] = ContactMessage.objects.all()
    assert message.sender == sender
    assert message.recipient_id == person.recipient_id
    assert message.subject == ContactSubject.OTHER
    assert message.custom_subject == "Échange de pratiques"
    assert not hasattr(message, "body")
    [email] = mailoutbox
    assert email.to == [person.email]
    assert str(make_header(decode_header(email.from_email))) == (
        f"{sender.get_full_name()} (via la Plateforme de l’inclusion) <noreply@inclusion.beta.gouv.fr>"
    )
    assert email.reply_to == [sender.email]
    assert "Ce contenu ne doit pas être enregistré." in email.body
    assert "Échange de pratiques" in email.subject
    assert (
        "E-mail envoyé depuis la Plateforme de l’inclusion. Répondez directement à cet e-mail pour répondre à "
        f"{sender.get_full_name()} ({sender.company_set.get()})."
    ) in email.body


def test_custom_subject_is_required(client):
    _, _, _, person = get_target_person(client)

    response = client.post(
        reverse("directory:send_message", kwargs={"key": person.key}),
        {"subject": ContactSubject.OTHER, "body": "Bonjour", "back_url": ""},
    )

    assert response.status_code == 200
    assertContains(response, "Précisez l'objet de votre message.", html=True)
    assert not ContactMessage.objects.exists()


def test_custom_subject_is_ignored_for_predefined_subject(client, mailoutbox):
    _, _, _, person = get_target_person(client)

    response = client.post(
        reverse("directory:send_message", kwargs={"key": person.key}),
        {
            "subject": ContactSubject.MEETING,
            "custom_subject": "Objet injecté",
            "body": "Bonjour",
            "back_url": "",
        },
    )

    assert response.status_code == 302
    message = ContactMessage.objects.get()
    assert message.custom_subject == ""
    assert "Objet injecté" not in mailoutbox[0].body


def test_message_rate_limit_is_per_user(client, mailoutbox, mocker):
    sender, _, _, person = get_target_person(client)
    caches["failsafe"].delete(f"directory-message-throttle-{sender.pk}")
    mocker.patch("itou.www.directory_views.views.MESSAGE_RATE_LIMIT", 1)
    url = reverse("directory:send_message", kwargs={"key": person.key})
    data = {"subject": ContactSubject.MEETING, "body": "Bonjour", "back_url": ""}

    assert client.post(url, data).status_code == 302
    response = client.post(url, data)

    assertContains(response, "Vous avez atteint la limite de 50 messages envoyés par jour.")
    assert ContactMessage.objects.count() == 1
    assert len(mailoutbox) == 1
