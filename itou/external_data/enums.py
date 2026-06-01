import enum


class RetrievalStatus(enum.StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    PENDING = "PENDING"
    FAILED = "FAILED"
