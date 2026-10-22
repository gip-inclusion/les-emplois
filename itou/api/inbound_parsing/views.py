import logging
from email.headerregistry import Address

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, views
from rest_framework.response import Response

from itou.api.auth import BrevoTokenAuthentication
from itou.api.inbound_parsing.enums import InboundParsingKind
from itou.api.inbound_parsing.serializers import EmailsPayloadSerializer
from itou.insertion.models import MobilizationEmail
from itou.utils.apis.exceptions import InboundParsingValueError
from itou.utils.apis.inbound_parsing import get_parsed_inbound_parsing_address
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.brand import product_name


logger = logging.getLogger(__name__)


def handle_service_answer_email(email):
    kind, key = get_parsed_inbound_parsing_address(email)
    from_email_address = email["From"]["Address"]

    try:
        mobilization_email = (
            MobilizationEmail.objects.filter(inbound_parsing_key=key)
            .select_related("service", "sender", "sender_prescriber_organization", "sender_company")
            .get()
        )
    except MobilizationEmail.DoesNotExist:
        logger.error("no mobilization_email found for inbound parsing address (kind=%s, key=%s)", kind, key)
        return

    if mobilization_email.answered_at is not None:
        logger.info(
            "mobilization_email=%d already got an answer with inbound parsing address (kind=%s, key=%s)",
            mobilization_email.pk,
            kind,
            key,
        )
    else:
        mobilization_email.answered_at = timezone.now()
        mobilization_email.save(update_fields=["answered_at"])
        if mobilization_email.service.contact_email != email["From"]["Address"]:
            logger.info(
                "service=%s replied to mobilization_email=%d with an address different from contact_email",
                mobilization_email.service.uid,
                mobilization_email.pk,
            )

    if mobilization_email.service.contact_email != from_email_address:
        logger.info(
            "service=%s replied to mobilization_email=%d with an address different from contact_email",
            mobilization_email.service.uid,
            mobilization_email.pk,
        )

    # Always send the message to the orientation sender
    parts = [email.get("ExtractedMarkdownMessage"), email.get("ExtractedMarkdownSignature")]
    message = "\n".join([part for part in parts if part]) or email.get("RawTextBody") or ""
    from_name = email["From"].get("Name")
    from_address = email["From"]["Address"]
    from_email = Address(
        display_name=f"{from_name} {product_name('via')}" if from_name else "", addr_spec=settings.DEFAULT_FROM_EMAIL
    )
    reply_to = Address(display_name=from_name or "", addr_spec=from_address)
    mobilization_email.free_form_email_to_sender(body_message=message, from_email=from_email, reply_to=reply_to).send()


KIND_MAPPING = {InboundParsingKind.SERVICE_ANSWER: handle_service_answer_email}


@extend_schema(exclude=True)
class BrevoInboundParsingView(LoginNotRequiredMixin, views.APIView):
    authentication_classes = (BrevoTokenAuthentication,)

    def post(self, request, *args, **kwargs):
        """
        Processes the events sent by Brevo. If anything goes wrong, don’t do anything and report it to Brevo
        by raising exceptions and 400 or 500 status code.
        This way we remain somewhat in sync with Brevo, whose API allows to list failed events.
        """
        request_serializer = EmailsPayloadSerializer(data=request.data)
        if not request_serializer.is_valid(raise_exception=False):
            # Handle the error ourselves to trigger an alert on Sentry
            errors = request_serializer.errors
            logger.error("could not parse request, error=%s", errors)
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        data = request_serializer.data
        for email in data["items"]:
            kind, key = get_parsed_inbound_parsing_address(email)
            if func := KIND_MAPPING.get(kind):
                func(email)
            else:
                raise InboundParsingValueError(
                    f"inbound parsing address (kind={kind}, key={key}) matched no inbound parsing kind"
                )

        return Response({"msg": "ok"}, status=status.HTTP_200_OK)
