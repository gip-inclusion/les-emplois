def get_choices_label(choices, value):
    # Inspired from ChoiceField.valid_value method
    text_value = str(value)
    for k, v in choices:
        if isinstance(v, (list, tuple)):
            # This is an optgroup, so look inside the group for options
            for k2, v2 in v:
                if value == k2 or text_value == str(k2):
                    return v2
        else:
            if value == k or text_value == str(k):
                return v
    return None  # We might want to raise an exception here instead
