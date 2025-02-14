import enum


class JobSeekerSessionKinds(enum.StrEnum):
    CHECK_NIR_JOB_SEEKER = "job-seeker-check-nir-job-seeker"
    GET_OR_CREATE = "job-seeker-get-or-create"
    UPDATE = "job-seeker-update"


class JobSeekerOrder(enum.StrEnum):
    FULL_NAME_ASC = "full_name"
    FULL_NAME_DESC = "-full_name"
    LAST_UPDATED_AT_ASC = "last_updated_at"
    LAST_UPDATED_AT_DESC = "-last_updated_at"
    JOB_APPLICATIONS_NB_ASC = "job_applications_nb"
    JOB_APPLICATIONS_NB_DESC = "-job_applications_nb"

    @property
    def opposite(self):
        if self.value.startswith("-"):
            return self.__class__(self.value[1:])
        else:
            return self.__class__(f"-{self.value}")

    # Make the Enum work in Django's templates
    # See:
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)
