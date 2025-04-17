import enum


class ItouEnvironment(enum.StrEnum):
    PROD = "PROD"
    DEMO = "DEMO"
    PENTEST = "PENTEST"
    REVIEW_APP = "REVIEW-APP"
    FAST_MACHINE = "FAST-MACHINE"
    DEV = "DEV"


# https://app.brevo.com/contact/list-listing
class BrevoListID(enum.IntEnum):
    LES_EMPLOIS = 31
    CANDIDATS = 82
    CANDIDATS_AUTONOMES_BLOQUES = 83
