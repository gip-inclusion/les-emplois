import secrets


def generate_random_token():
    """
    Returns a random token of 6 chars.
    https://docs.python.org/3/library/secrets.html#secrets.token_hex
    E.g.:
        F0915B
        034846
        09F94D
        C50364
        etc.
    """
    return secrets.token_hex(3).upper()
