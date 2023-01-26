from datetime import timedelta

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import DateRangeField, ranges
from django.db import models
from django.db.models import Func

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


class AbstractSupportRemark(models.Model):
    class Meta:
        verbose_name = "Commentaire du support"
        abstract = True

    remark = models.TextField(verbose_name="Commentaire", blank=True)

    # Attachment to different model types
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")


class PkSupportRemark(AbstractSupportRemark):
    object_id = models.PositiveIntegerField()


class UUIDSupportRemark(AbstractSupportRemark):
    object_id = models.UUIDField()
