from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class NullIfEmptyCharField(serializers.CharField):
    def to_representation(self, value):
        if value == "":
            return None
        return super().to_representation(value)


@extend_schema_field(OpenApiTypes.NONE)
class NullField(serializers.Field):
    def to_representation(self, _):
        # Always replace by `None`.
        return None

    def get_attribute(self, _):
        # Do not attempt to match field name in instance
        return None
