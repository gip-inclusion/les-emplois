import enum


class LogoutWarning(enum.StrEnum):
    FT_NO_FT_ORGANIZATION = "ft_no_ft_organization"
    NO_ORGANIZATION = "no_organization"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)
