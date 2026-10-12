import enum


class InboundParsingKind(enum.StrEnum):
    # When a service provider answers an email sent by a professional
    SERVICE_ANSWER = "sa"
