from urllib.parse import quote

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from itou.utils.emails import redact_email_address


def format_error_modal_content(message_body, action_url, action_text, dismiss_text="Retour"):
    return format_html(
        '<div class="modal-body">'
        "{}"
        "</div>"
        '<div class="modal-footer">'
        '<button type="button" class="btn btn-sm btn-link" data-bs-dismiss="modal">{}</button>'
        '<a href="{}" class="btn btn-sm btn-primary">{}</a>'
        "</div>",
        message_body,
        dismiss_text,
        action_url,
        action_text,
    )


def redirect_with_error_sso_email_conflict_on_registration(request, user, sso_name):
    redirect_url = reverse("signup:choose_user_kind")
    messages.error(
        request,
        format_error_modal_content(
            format_html(
                "<p>L’inscription via {} a échoué car un compte existe déjà avec l’adresse email "
                "{} mais avec un mode de connexion différent.</p><p>Pour accéder à votre compte "
                "cliquez sur le bouton <strong>“Je me connecte avec ce compte”</strong>.</p>"
                '<p>Si ce compte n’est pas le vôtre, cliquez sur <strong>"Retour"</strong> et utilisez une autre '
                "adresse email pour vous inscrire.</p>",
                sso_name,
                redact_email_address(user.email),
            ),
            f"{reverse('login:existing_user', args=(user.public_id,))}?back_url={quote(redirect_url)}",
            "Je me connecte avec ce compte",
        ),
        extra_tags="modal sso_email_conflict_registration_failure",
    )
    return HttpResponseRedirect(redirect_url)
