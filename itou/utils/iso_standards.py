import enum


@enum.unique
class Sex(enum.StrEnum):
    """ISO/IEC 5218"""

    NOT_KNOWN = "0"
    MALE = "1"
    FEMALE = "2"
    NOT_APPLICABLE = "9"
