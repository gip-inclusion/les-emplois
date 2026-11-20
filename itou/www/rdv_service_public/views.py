import logging
import secrets

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_GET, require_POST

from itou.job_applications.models import JobApplication
from itou.rdv_service_public.models import AppointmentProposal, OAuthToken
from itou.utils.apis.rdv_service_public import (
    RdvServicePublicApiError,
    RdvServicePublicInvalidTokenError,
    RdvServicePublicRequestRefusedError,
    get_api_client,
    get_oauth_client,
)
from itou.utils.auth import check_request
from itou.utils.brand import product_name
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)

OAUTH_SESSION_KEY = "rdv_service_public_oauth"
UNAVAILABLE_MESSAGE = "RDV Service Public est momentanément indisponible. Merci de réessayer plus tard."
REQUEST_FAILED_MESSAGE = "Votre demande n'a pas pu aboutir."


def _get_job_application(request, job_application_id):
    job_application = get_object_or_404(
        JobApplication.objects.is_active_company_member(request.user).select_related("job_seeker", "to_company"),
        pk=job_application_id,
    )
    if not job_application.to_company.can_use_rdv_service_public:
        raise Http404
    return job_application


def _get_job_application_url(request, job_application):
    path = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    return get_absolute_url(path, host=request.get_host())


def _get_redirect_uri(request):
    # On the host of the request, where the session holding the OAuth state lives
    return get_absolute_url(reverse("rdv_service_public:oauth_callback"), host=request.get_host())


def _redirect_with_error(request, job_application, message):
    messages.error(request, message)
    return HttpResponseRedirect(_get_job_application_url(request, job_application))


def _get_error_message(exc):
    # Sending a refused request again would not help, unlike a request to an unavailable server
    if isinstance(exc, RdvServicePublicRequestRefusedError):
        return REQUEST_FAILED_MESSAGE
    return UNAVAILABLE_MESSAGE


def _redirect_to_rdv_service_public_login(request, job_application):
    state = secrets.token_urlsafe(32)
    request.session[OAUTH_SESSION_KEY] = {"state": state, "job_application_id": str(job_application.pk)}
    authorize_url = get_oauth_client().get_authorize_url(redirect_uri=_get_redirect_uri(request), state=state)
    return HttpResponseRedirect(authorize_url)


def _propose_appointment(request, job_application, access_token, *, can_link_account_again):
    job_seeker = job_application.job_seeker
    company = job_application.to_company
    job_application_url = _get_job_application_url(request, job_application)
    try:
        rdv_plan = get_api_client(access_token).create_rdv_plan(
            user={
                # A single RDV Service Public user per job seeker and company
                "external_id": f"{job_seeker.public_id}-{company.pk}",
                "first_name": job_seeker.first_name,
                "last_name": job_seeker.last_name,
                "email": job_seeker.email,
                "phone_number": job_seeker.phone,
                "address": job_seeker.address_on_one_line,
            },
            return_url=job_application_url,
            dossier_url=job_application_url,
        )
    except RdvServicePublicApiError as exc:
        if isinstance(exc, RdvServicePublicInvalidTokenError):
            # The user revoked the access in RDV Service Public
            OAuthToken.objects.filter(user=request.user).delete()
            # Never right after linking the account, to avoid a redirection loop
            if can_link_account_again:
                return _redirect_to_rdv_service_public_login(request, job_application)
        if isinstance(exc, RdvServicePublicRequestRefusedError) and "phone_number" in exc.invalid_fields:
            # The phone number is free text in Les Emplois, RDV Service Public checks it
            return _redirect_with_error(
                request,
                job_application,
                "RDV Service Public n'accepte pas le numéro de téléphone du candidat. "
                "Corrigez-le via Modifier, puis recommencez.",
            )
        logger.exception("Error creating a rdv_plan in RDV Service Public")
        return _redirect_with_error(request, job_application, _get_error_message(exc))

    AppointmentProposal.objects.create(
        job_application=job_application,
        company=company,
        job_seeker=job_seeker,
        created_by=request.user,
        rdv_service_public_plan_id=rdv_plan.id,
        rdv_service_public_user_id=rdv_plan.user_id,
    )
    return HttpResponseRedirect(rdv_plan.url)


@transaction.non_atomic_requests  # refresh_access_token() commits the new token in its own transaction
@check_request(lambda request: request.from_employer)
@require_POST
def propose_appointment(request, job_application_id):
    job_application = _get_job_application(request, job_application_id)
    if not job_application.job_seeker.email:
        # RDV Service Public sends invitations by email only
        return _redirect_with_error(
            request,
            job_application,
            "Le candidat doit avoir une adresse e-mail pour que vous puissiez lui proposer un rendez-vous.",
        )

    token = OAuthToken.objects.filter(user=request.user).first()
    if token and token.needs_refresh:
        try:
            token.refresh_access_token()
        except RdvServicePublicInvalidTokenError:
            token.delete()
            token = None
        except RdvServicePublicApiError as exc:
            logger.exception("Error refreshing a RDV Service Public token")
            return _redirect_with_error(request, job_application, _get_error_message(exc))
    if token is None:
        return _redirect_to_rdv_service_public_login(request, job_application)
    return _propose_appointment(request, job_application, token.access_token, can_link_account_again=True)


@transaction.non_atomic_requests  # Like propose_appointment(), which it resumes
@check_request(lambda request: request.from_employer)
@require_GET
def oauth_callback(request):
    # The OAuth state can only be used once
    oauth_session = request.session.pop(OAUTH_SESSION_KEY, None)
    if not oauth_session or not constant_time_compare(request.GET.get("state", ""), oauth_session["state"]):
        messages.error(request, "Une erreur technique est survenue. Merci de recommencer.")
        return HttpResponseRedirect(reverse("dashboard:index"))
    job_application = _get_job_application(request, oauth_session["job_application_id"])

    if error := request.GET.get("error"):
        if error == "access_denied":
            return _redirect_with_error(
                request,
                job_application,
                f"Vous devez autoriser {product_name()} à accéder à RDV Service Public pour proposer un rendez-vous.",
            )
        logger.error("RDV Service Public authorization failed: %s", error)
        return _redirect_with_error(request, job_application, UNAVAILABLE_MESSAGE)

    try:
        token_data = get_oauth_client().get_token(
            code=request.GET.get("code", ""), redirect_uri=_get_redirect_uri(request)
        )
        agent = get_api_client(token_data.access_token).get_me()
    except RdvServicePublicApiError as exc:
        logger.exception("Error linking a RDV Service Public account")
        return _redirect_with_error(request, job_application, _get_error_message(exc))

    # RDV Service Public authorizes the agent already logged in the browser, who may be a colleague
    if agent.email.lower() != request.user.email.lower():
        return _redirect_with_error(
            request,
            job_application,
            f"Vous êtes connecté à RDV Service Public avec le compte {agent.email}. "
            "Déconnectez-vous de RDV Service Public, puis recommencez.",
        )

    OAuthToken.save_for_user(request.user, token_data, agent_id=agent.id)
    return _propose_appointment(request, job_application, token_data.access_token, can_link_account_again=False)
