class ASPReferenceError(Exception):
    "Generic error class for what may go wrong in this app (a lot of things actually)"


class UnknownCommuneError(ASPReferenceError):
    "Unable to lookup commune. May happen from time to time as itou and ASP INSEE references are not synced"


class CommuneUnknownInPeriodError(ASPReferenceError):
    "Unable to find a commune for a given period"
