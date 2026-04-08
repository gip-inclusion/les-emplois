def format_address_on_one_line(obj):
    """
    Format a French postal address on one line for display.

    Expects an object with attributes ``address_line_1``, ``address_line_2``,
    ``post_code``, and ``city`` (same semantics as ``AddressMixin``).

    Returns ``None`` unless ``address_line_1``, ``post_code``, and ``city`` are all truthy.
    """
    if not all([obj.address_line_1, obj.post_code, obj.city]):
        return None
    fields = [
        obj.address_line_1,
        obj.address_line_2,
        f"{obj.post_code} {obj.city}",
    ]
    return ", ".join(field for field in fields if field)
