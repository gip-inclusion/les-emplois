from itou.approvals.enums import ProlongationReason


# A prolongation report file can be uploaded only for these reasons
PROLONGATION_REPORT_FILE_REASONS = (
    ProlongationReason.RQTH,
    ProlongationReason.SENIOR,
    ProlongationReason.PARTICULAR_DIFFICULTIES,
)
