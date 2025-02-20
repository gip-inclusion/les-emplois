import datetime
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from itou.companies.models import Company
from itou.rdv_insertion.api import get_invitation_status
from itou.rdv_insertion.models import Appointment, Invitation, InvitationRequest, Location, Participation, WebhookEvent
from itou.utils.auth import check_user
from itou.utils.urls import get_safe_url


logger = logging.getLogger("itou.rdv_insertion")


class SignatureMissing(Exception):
    pass


class InvalidSignature(Exception):
    pass


class UnsupportedEvent(Warning):
    pass


@require_POST
@csrf_exempt
@login_not_required
def webhook(request):
    try:
        # FIXME: RDV-I encodings should be consistent
        try:
            request.body.decode()
            body = request.body
            logger.info("Payload encoding is UTF-8")
        except UnicodeDecodeError:
            body = request.body.decode("latin-1").encode()
            logger.warning("Payload encoding is LATIN-1")

        if not (given_signature := request.headers.get("x-rdvi-signature")):
            raise SignatureMissing

        signature = hmac.new(settings.RDV_INSERTION_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, given_signature):
            raise InvalidSignature

        event_data = json.loads(body)
        event = WebhookEvent.objects.create(
            body=event_data,
            headers=dict(request.headers),
        )

        # TODO: handle the following code in a huey task

        if event.for_appointment:
            rdvs_company_id = event.body["data"]["organisation"]["rdv_solidarites_organisation_id"]
            rdvi_user_ids = [user["id"] for user in event.body["data"]["users"]]
            invitation_requests = InvitationRequest.objects.filter(
                company__rdv_solidarites_id=rdvs_company_id, rdv_insertion_user_id__in=rdvi_user_ids
            )
            if invitation_requests.exists():
                with transaction.atomic():
                    location, _ = Location.objects.update_or_create(
                        rdv_solidarites_id=event.body["data"]["lieu"]["rdv_solidarites_lieu_id"],
                        defaults=dict(
                            name=event.body["data"]["lieu"]["name"],
                            address=event.body["data"]["lieu"]["address"],
                            phone_number=event.body["data"]["lieu"]["phone_number"],
                        ),
                    )
                    appointment, _ = Appointment.objects.update_or_create(
                        company=Company.objects.get(rdv_solidarites_id=rdvs_company_id),
                        rdv_insertion_id=event.body["data"]["id"],
                        defaults=dict(
                            status=Appointment.Status(event.body["data"]["status"]),
                            reason_category=Appointment.ReasonCategory(
                                event.body["data"]["motif"]["motif_category"]["short_name"]
                            ),
                            reason=event.body["data"]["motif"]["name"],
                            is_collective=event.body["data"]["motif"]["collectif"],
                            start_at=datetime.datetime.fromisoformat(event.body["data"]["starts_at"]),
                            duration=datetime.timedelta(minutes=event.body["data"]["duration_in_min"]),
                            canceled_at=(
                                datetime.datetime.fromisoformat(event.body["data"]["cancelled_at"])
                                if event.body["data"]["cancelled_at"]
                                else None
                            ),
                            address=event.body["data"]["address"],
                            total_participants=event.body["data"]["users_count"],
                            max_participants=event.body["data"]["max_participants_count"],
                            location=location,
                        ),
                    )

                    # The participations key is not always present in the payload
                    # We assume the users list contains the participation user list
                    # and fallback on participations for extra data
                    for invitation_request in invitation_requests:
                        defaults = {
                            "rdv_insertion_user_id": invitation_request.rdv_insertion_user_id,
                        }
                        participation_data = next(
                            (
                                d
                                for d in event.body["data"].get("participations")
                                if d and d["user"]["id"] == invitation_request.rdv_insertion_user_id
                            ),
                            None,
                        )
                        if participation_data:
                            defaults["status"] = Participation.Status(participation_data["status"])
                            defaults["rdv_insertion_id"] = participation_data["id"]

                        Participation.objects.update_or_create(
                            job_seeker=invitation_request.job_seeker,
                            appointment=appointment,
                            defaults=defaults,
                        )

                    # Flag event processed
                    event.is_processed = True
                    event.save(update_fields=["is_processed"])
            else:
                logger.info(f"No invitation requests matching {rdvs_company_id=}, {rdvi_user_ids=}")
        elif event.for_invitation:
            try:
                # Invitations are created synchronously when calling RDV-I create_adn_invite endpoint
                invitation = Invitation.objects.get(rdv_insertion_id=event.body["data"]["id"])
            except Invitation.DoesNotExist:
                logger.info(f"No invitations matching rdv_insertion_id={event.body['data']['id']}")
            else:
                with transaction.atomic():
                    updated_fields = []
                    if invitation_status := get_invitation_status(event.body["data"]):
                        invitation.status = invitation_status
                        updated_fields.append("status")
                    if event.body["data"]["delivered_at"]:
                        invitation.delivered_at = datetime.datetime.fromisoformat(event.body["data"]["delivered_at"])
                        updated_fields.append("delivered_at")
                    if updated_fields:
                        invitation.save(update_fields=updated_fields)

                    # Flag event processed
                    event.is_processed = True
                    event.save(update_fields=["is_processed"])
        else:
            raise UnsupportedEvent(event.body["meta"]["model"])

        return JsonResponse({"success": True})
    except Exception as e:
        logger.exception("Error while handling RDVI webhook")
        response = JsonResponse({"success": False})
        if isinstance(e, SignatureMissing | InvalidSignature):
            response.status_code = 401
        else:
            response.status_code = 400
        return response


@check_user(lambda user: user.is_employer)
def discover(request):
    return render(
        request,
        "rdv_insertion/discover.html",
        {
            "back_url": get_safe_url(request, "back_url", fallback_url=reverse("apply:list_for_siae")),
        },
    )
