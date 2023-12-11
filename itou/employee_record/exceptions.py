class SerializationError(Exception):
    """Mainly raised during serialization phases in employee record management commands."""


class InvalidStatusError(Exception):
    """Raised when changing status from an invalid previous status value."""
