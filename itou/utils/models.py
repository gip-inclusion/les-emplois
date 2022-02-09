from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import DateRangeField
from django.db import models
from django.db.models import Func


class DateRange(Func):
    """
    Expression used to setup PostgreSQL specific database constraints for
    models that defines a date range using 2 fields instead of the native
    PostgreSQL DateRangeField.

    https://docs.djangoproject.com/en/3.1/ref/contrib/postgres/constraints/
    """

    function = "daterange"
    output_field = DateRangeField()


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
