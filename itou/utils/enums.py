import enum


class ItouEnvironment(enum.StrEnum):
    PROD = "PROD"
    DEMO = "DEMO"
    PENTEST = "PENTEST"
    REVIEW_APP = "REVIEW-APP"
    FAST_MACHINE = "FAST-MACHINE"
    DEV = "DEV"
