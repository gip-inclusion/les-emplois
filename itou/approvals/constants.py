import datetime

from itou.approvals.enums import ProlongationReason


# A pending job application created within this period blocks employer-initiated PASS IAE closure.
CLOSURE_PENDING_APPLICATION_MAX_AGE = datetime.timedelta(days=60)


# A prolongation report file can be uploaded only for these reasons
PROLONGATION_REPORT_FILE_REASONS = (
    ProlongationReason.RQTH,
    ProlongationReason.SENIOR,
    ProlongationReason.PARTICULAR_DIFFICULTIES,
)
