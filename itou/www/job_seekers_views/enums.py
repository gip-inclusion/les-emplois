from enum import StrEnum


class JobSeekerSessionKinds(StrEnum):
    CHECK_NIR_JOB_SEEKER = "job-seeker-check-nir-job-seeker"
    GET_OR_CREATE = "job-seeker-get-or-create"
    UPDATE = "job-seeker-update"
