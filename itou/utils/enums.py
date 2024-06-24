import enum


class ItouEnvironment(enum.StrEnum):
    PROD = "PROD"
    DEMO = "DEMO"
    REVIEW_APP = "REVIEW-APP"
    FAST_MACHINE = "FAST-MACHINE"
    DEV = "DEV"
