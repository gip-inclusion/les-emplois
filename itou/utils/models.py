from datetime import timedelta

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField, DateRangeField, ranges
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import F, Func, Q, Transform

from itou.utils.triggers import FieldsHistory
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
    updated_at = models.DateTimeField(auto_now=True, verbose_name="mis à jour le", null=True)


class PkSupportRemark(AbstractSupportRemark):
    object_id = models.PositiveIntegerField()


class UUIDSupportRemark(AbstractSupportRemark):
    object_id = models.UUIDField()


def check_nullable_date_order_constraint(
    prior_date_field,
    later_date_field,
    *,
    allow_equal=True,
    name,
    violation_error_code=None,
    violation_error_message=None,
):
    operator = "gte" if allow_equal else "gt"
    condition = Q(**{f"{later_date_field}__isnull": True}) | Q(
        **{f"{prior_date_field}__isnull": False, f"{later_date_field}__{operator}": F(prior_date_field)}
    )
    return models.CheckConstraint(
        name=name,
        condition=condition,
        violation_error_code=violation_error_code,
        violation_error_message=violation_error_message,
    )


class AbstractFieldsHistoryModel(models.Model):
    FIELDS_HISTORY_TRIGGER_NAME = None
    FIELDS_HISTORY_TRIGGER_FIELDS = None

    fields_history = ArrayField(
        models.JSONField(
            encoder=DjangoJSONEncoder,
        ),
        verbose_name="historique des champs modifiés sur le modèle",
        default=list,
        db_default=[],
    )

    class Meta:
        abstract = True

    def __init_subclass__(cls, /, **kwargs):
        triggers = getattr(cls.Meta, "triggers", [])
        triggers.append(
            FieldsHistory(
                name=cls.FIELDS_HISTORY_TRIGGER_NAME,
                fields=cls.FIELDS_HISTORY_TRIGGER_FIELDS,
            )
        )
        setattr(cls.Meta, "triggers", triggers)
        super().__init_subclass__(**kwargs)

    def _do_update(
        self,
        base_qs,
        using,
        pk_val,
        values,
        update_fields,
        forced_update,
        returning_fields,
    ):
        history_field = self._meta.get_field("fields_history")
        # Prevent Django from trying to update fields_history in a save
        values = [(f, v1, v2) for f, v1, v2 in values if f != history_field]
        # Get new history field value in return
        if history_field not in returning_fields:
            returning_fields.append(history_field)
        return super()._do_update(
            base_qs,
            using,
            pk_val,
            values,
            update_fields,
            forced_update,
            returning_fields,
        )
