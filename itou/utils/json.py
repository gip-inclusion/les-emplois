import datetime
import decimal
import json
import uuid

import django.db.models
import django.utils.dateparse
import django.utils.duration
import django.utils.functional
import django.utils.timezone


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        # Code mostly taken from django.core.serializers.json.DjangoJSONEncoder
        # See "Date Time String Format" in the ECMA-262 specification.
        if isinstance(obj, datetime.datetime):
            return {"__type__": "datetime.datetime", "value": obj.isoformat()}
        if isinstance(obj, datetime.date):
            return {"__type__": "datetime.date", "value": obj.isoformat()}
        if isinstance(obj, datetime.time):
            return {"__type__": "datetime.time", "value": obj.isoformat()}
        if isinstance(obj, datetime.timedelta):
            return {"__type__": "datetime.timedelta", "value": django.utils.duration.duration_iso_string(obj)}
        if isinstance(obj, decimal.Decimal):
            return {"__type__": "decimal.Decimal", "value": str(obj)}
        if isinstance(obj, uuid.UUID):
            return {"__type__": "uuid.UUID", "value": str(obj)}
        if isinstance(obj, django.utils.functional.Promise):
            return str(obj)
        if isinstance(obj, django.db.models.Model):
            return obj.pk

        # Let the base class default method raise the TypeError
        return super().default(obj)


class JSONDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("object_hook", self._decode_object)
        super().__init__(*args, **kwargs)

    @staticmethod
    def _decode_object(obj):
        if "__type__" not in obj:  # Not serialized by our JSONEncoder
            return obj

        if obj["__type__"] == "datetime.datetime":
            return datetime.datetime.fromisoformat(obj["value"])
        if obj["__type__"] == "datetime.date":
            return datetime.date.fromisoformat(obj["value"])
        if obj["__type__"] == "datetime.time":
            return datetime.time.fromisoformat(obj["value"])
        if obj["__type__"] == "datetime.timedelta":
            return django.utils.dateparse.parse_duration(obj["value"])
        if obj["__type__"] == "decimal.Decimal":
            return decimal.Decimal(obj["value"])
        if obj["__type__"] == "uuid.UUID":
            return uuid.UUID(obj["value"])

        return obj
