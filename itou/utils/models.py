from datetime import timedelta

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import DateRangeField, ranges
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Func, Transform

from itou.utils.types import InclusiveDateRange


class DateRange(Func):
    """
    Expression used to setup PostgreSQL specific database constraints for
    models that defines a date range using 2 fields instead of the native
    PostgreSQL DateRangeField.

    https://docs.djangoproject.com/en/3.1/ref/contrib/postgres/constraints/
    """

    function = "daterange"
    output_field = DateRangeField()


class InclusiveDateRangeField(DateRangeField):
    range_type = InclusiveDateRange

    def from_db_value(self, value, expression, connection):
        if value:
            # Default bounds are [] but database returns [),
            # convert upper bound accordingly.
            lower, upper = value.lower, value.upper
            if upper:
                upper -= timedelta(days=1)
            value = InclusiveDateRange(lower, upper)
        return value


@InclusiveDateRangeField.register_lookup
class InclusiveRangeEndsWith(ranges.RangeEndsWith):
    def as_sql(self, compiler, connection):
        sql, params = super().as_sql(compiler, connection)
        return f"({sql} - interval '1 day')::date", params


@InclusiveDateRangeField.register_lookup
class Upper(Transform):
    lookup_name = "upper"
    function = "UPPER"


class SlylyImmutableUnaccent(Transform):
    """
    unaccent function falsely declared as immutable to be usable in index & generated fields
    It is not immutable.
    """

    bilateral = True
    lookup_name = "slyly_immutable_unaccent"
    function = "SLYLY_IMMUTABLE_UNACCENT"


class AbstractSupportRemark(models.Model):
    class Meta:
        verbose_name = "commentaire du support"
        abstract = True

    remark = models.TextField(verbose_name="commentaire", blank=True)

    # Attachment to different model types
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")


class PkSupportRemark(AbstractSupportRemark):
    object_id = models.PositiveIntegerField()


class UUIDSupportRemark(AbstractSupportRemark):
    object_id = models.UUIDField()


# This class can be dropped once https://github.com/django/django/pull/16560 is merged & released
class UniqueConstraintWithErrorCode(models.UniqueConstraint):
    def __init__(self, *args, validation_error_code, **kwargs):
        super().__init__(*args, **kwargs)
        self.validation_error_code = validation_error_code

    def validate(self, *args, **kwargs):
        try:
            return super().validate(*args, **kwargs)
        except ValidationError as ve:
            if not ve.code:
                ve.code = self.validation_error_code
            raise ve

    def deconstruct(self):
        path, args, kwargs = super().deconstruct()
        if self.validation_error_code:
            kwargs["validation_error_code"] = self.validation_error_code
        return path, args, kwargs
