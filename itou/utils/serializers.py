from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class NullIfEmptyCharField(serializers.CharField):
    def __init__(self, truncate=None, **kwargs):
        self.truncate = truncate
        super().__init__(**kwargs)

    def to_representation(self, value):
        if value == "":
            return None
        representation = super().to_representation(value)
        if self.truncate:
            representation = representation[: self.truncate]
        return representation


class NullIfEmptyChoiceField(serializers.ChoiceField):
    def to_representation(self, value):
        if value == "":
            return None
        return super().to_representation(value)


class DefaultIfEmptyChoiceField(serializers.ChoiceField):
    def to_representation(self, value):
        return super().to_representation(self.default if value == "" else value)


@extend_schema_field(OpenApiTypes.NONE)
class NullField(serializers.Field):
    def to_representation(self, _):
        # Always replace by `None`.
        return None

    def get_attribute(self, _):
        # Do not attempt to match field name in instance
        return None
