import secrets


def generate_random_token(n=6):
    """
    Returns a random token of n chars.
    https://docs.python.org/3/library/secrets.html#secrets.token_hex
    E.g.:
        F0915B
        034846
        09F94D
        C50364
        etc.
    """
    # Little arithmetic trick for odd numbers.
    return secrets.token_hex(1 + n // 2)[:n].upper()
