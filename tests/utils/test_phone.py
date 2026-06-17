import pytest

from itou.utils.phone import normalize_phone_number


@pytest.mark.parametrize(
    "phone,expected",
    [
        ("", None),
        ("0601901570", "0601901570"),
        ("06 01 90 15 70", "0601901570"),
        ("+33601901570", "0601901570"),
        ("+33 6 01 90 15 70", "0601901570"),
        ("0033601901570", "0601901570"),
        ("123", None),
        ("+336019015701", None),
    ],
)
def test_normalize_phone_number(phone, expected):
    assert normalize_phone_number(phone) == expected
