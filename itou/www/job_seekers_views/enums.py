import enum

from itou.utils.ordering import OrderEnum


class JobSeekerSessionKinds(enum.StrEnum):
    CHECK_NIR_JOB_SEEKER = "job-seeker-check-nir-job-seeker"
    GET_OR_CREATE = "job-seeker-get-or-create"
    UPDATE = "job-seeker-update"


class JobSeekerOrder(OrderEnum):
    FULL_NAME_ASC = "full_name"
    FULL_NAME_DESC = "-full_name"
    LAST_UPDATED_AT_ASC = "last_updated_at"
    LAST_UPDATED_AT_DESC = "-last_updated_at"
    JOB_APPLICATIONS_NB_ASC = "job_applications_nb"
    JOB_APPLICATIONS_NB_DESC = "-job_applications_nb"
