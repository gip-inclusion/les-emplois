import logging
from email.utils import parsedate_to_datetime

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, views
from rest_framework.response import Response

from itou.api.auth import BrevoTokenAuthentication
from itou.api.inbound_parsing.enums import InboundParsingKind
from itou.api.inbound_parsing.serializers import EmailsPayloadSerializer
from itou.insertion.models import MobilizationEmail
from itou.utils.apis.inbound_parsing import get_inbound_parsing_address, parse_inbound_parsing_address
from itou.utils.auth import LoginNotRequiredMixin


logger = logging.getLogger(__name__)


def handle_service_answer_email(email):
    inbound_parsing_address = get_inbound_parsing_address(email)
    key, _ = parse_inbound_parsing_address(inbound_parsing_address)
    try:
        sent_at = parsedate_to_datetime(email.get("SentAtDate")) or timezone.now()
    except ValueError:
        sent_at = timezone.now()

    try:
        mobilization_email = MobilizationEmail.objects.filter(inbound_parsing_key=key).select_related("service").get()
    except MobilizationEmail.DoesNotExist:
        logger.error("no mobilization_email found for inbound_parsing_address=%s", inbound_parsing_address)
        return

    if mobilization_email.answered_at is not None:
        logger.info(
            "mobilization_email=%d already got an answer with inbound_parsing_address=%s",
            mobilization_email.pk,
            inbound_parsing_address,
        )
    else:
        mobilization_email.answered_at = sent_at

        if mobilization_email.service.contact_email != email["From"]["Address"]:
            logger.info(
                "service=%s replied to mobilization_email=%d with an address different from contact_email",
                mobilization_email.service.uid,
                mobilization_email.pk,
            )
        mobilization_email.save(update_fields=["answered_at"])


KIND_MAPPING = {InboundParsingKind.SERVICE_ANSWER: handle_service_answer_email}


@extend_schema(exclude=True)
class BrevoInboundParsingView(LoginNotRequiredMixin, views.APIView):
    authentication_classes = (BrevoTokenAuthentication,)

    def post(self, request, *args, **kwargs):
        self.request_serializer = EmailsPayloadSerializer(data=request.data)
        if not self.request_serializer.is_valid(raise_exception=False):
            # Handle the error ourselves to trigger an alert on Sentry
            errors = self.request_serializer.errors
            logger.error("could not parse request, error=%s", errors)
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        data = self.request_serializer.data
        for email in data["items"]:
            inbound_parsing_address = get_inbound_parsing_address(email)
            _, kind = parse_inbound_parsing_address(inbound_parsing_address)
            if func := KIND_MAPPING.get(kind):
                func(email)
            else:
                logger.error("inbound_parsing_address=%s matched no inbound parsing kind", inbound_parsing_address)

        return Response({"msg": "ok"}, status=status.HTTP_200_OK)
