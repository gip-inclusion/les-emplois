import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import status, views
from rest_framework.response import Response

from itou.api.auth import BrevoTokenAuthentication
from itou.api.inbound_parsing.enums import InboundParsingKind
from itou.api.inbound_parsing.serializers import EmailsPayloadSerializer
from itou.insertion.enums import MobilizationEventKind
from itou.insertion.models import MobilizationEvent
from itou.utils.auth import LoginNotRequiredMixin


logger = logging.getLogger(__name__)


def get_inbound_parsing_address(email):
    """
    The documentations says Recipients is a list of Mailto (with an Address)
    but the given example says Recipients is a list of strings.
    https://developers.brevo.com/docs/inbound-parse-webhooks#parsed-email-payload
    """
    for recipient in email["Recipients"]:
        if isinstance(recipient, str):
            if f"@{settings.INBOUND_PARSING_SUBDOMAIN}".casefold() in recipient.casefold():
                return recipient.casefold()
        elif address := recipient.get("Address"):
            if f"@{settings.INBOUND_PARSING_SUBDOMAIN}".casefold() in address.casefold():
                return address.casefold()
    raise ValueError("Unable to find inbound parsing address.")


def parse_inbound_parsing_address(address):
    username = address.split("@")[0]
    split_username = username.split(".")
    if len(split_username) != 2:
        raise ValueError("Unable to parse inbound parsing address.")
    return split_username


def handle_service_answer_email(email):
    inbound_parsing_address = get_inbound_parsing_address(email)
    inbound_key = inbound_parsing_address.split("@")[0].split(".")[1]

    mobilization_events = MobilizationEvent.objects.filter(
        kind=MobilizationEventKind.SEND_EMAIL_TO_SERVICE, inbound_key=inbound_key
    ).select_related("service")

    now = timezone.now()
    events_to_update = []
    for mobilization_event in mobilization_events:
        if mobilization_event.service_answered_at is not None:
            logger.info(
                "mobilization_event=%d already got an answer with inbound_parsing_address=%s",
                mobilization_event.pk,
                inbound_parsing_address,
            )
        else:
            mobilization_event.service_answered_at = now
            events_to_update.append(mobilization_event)

            if mobilization_event.service.contact_email != email["From"]["Address"]:
                logger.info(
                    "service=%s replied to mobilization_event=%d with an address different from contact_email",
                    mobilization_event.service.uid,
                    mobilization_event.pk,
                )
    if not mobilization_events:
        logger.error("no mobilization_event found for inbound_parsing_address=%s", inbound_parsing_address)

    MobilizationEvent.objects.bulk_update(events_to_update, ["service_answered_at"])


KIND_MAPPING = {InboundParsingKind.SERVICE_ANSWER: handle_service_answer_email}


class BrevoInboundParsingView(LoginNotRequiredMixin, views.APIView):
    authentication_classes = (BrevoTokenAuthentication,)

    def post(self, request, *args, **kwargs):
        self.request_serializer = EmailsPayloadSerializer(data=request.data)
        self.request_serializer.is_valid(raise_exception=True)
        data = self.request_serializer.data
        for email in data["items"]:
            inbound_parsing_address = get_inbound_parsing_address(email)
            prefix = inbound_parsing_address.split(".")[0]
            if func := KIND_MAPPING.get(prefix):
                func(email)
            else:
                logger.error("inbound_parsing_address=%s matched no inbound parsing kind", inbound_parsing_address)

        return Response({"msg": "ok"}, status=status.HTTP_200_OK)
