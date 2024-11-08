import enum


class LogoutWarning(enum.StrEnum):
    EMPLOYER_NO_COMPANY = "employer_no_company"
    EMPLOYER_INACTIVE_COMPANY = "employer_inactive_company"
    FT_NO_FT_ORGANIZATION = "ft_no_ft_organization"
    LABOR_INSPECTOR_NO_INSTITUTION = "labor_inspector_no_institution"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)
