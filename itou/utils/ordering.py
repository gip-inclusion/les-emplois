import enum


class OrderEnum(enum.StrEnum):
    @property
    def opposite(self):
        if self.value.startswith("-"):
            return self.__class__(self.value[1:])
        else:
            return self.__class__(f"-{self.value}")

    @property
    def order_by(self):
        return (str(self), "-pk" if self.value.startswith("-") else "pk")

    # Make the Enum work in Django's templates
    # See:
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)
