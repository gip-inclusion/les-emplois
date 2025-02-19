"""
Serialize data to/from JSON while ignoring automatic fields (GeneratedField & auto_now* Date/Datetime fields)
"""

from django.core.serializers.json import Deserializer as JsonDeserializer, Serializer as JsonSerializer
from django.db.models import GeneratedField


class Serializer(JsonSerializer):
    """Convert a queryset to JSON while ignoring fields with automatic values."""

    def handle_field(self, obj, field):
        if (
            isinstance(field, GeneratedField)
            or getattr(field, "auto_now", False)
            or getattr(field, "auto_now_add", False)
        ):
            return
        super().handle_field(obj, field)


Deserializer = JsonDeserializer
