import decimal

import pytest

from itou.utils.numbers import round_number


@pytest.mark.parametrize(
    "number,expected",
    [
        (decimal.Decimal(1), decimal.Decimal("1")),
        (decimal.Decimal(1_000), decimal.Decimal("1000")),
        (decimal.Decimal("1.23"), decimal.Decimal("1.23")),
        # These tests are warranted because the default rounding
        # is not what one may expect:
        # >>> q = Decimal("0.01")
        # >>> Decimal("7.515").quantize(q)
        # Decimal('7.52')
        # >>> Decimal("7.525").quantize(q)
        # Decimal('7.52')
        (decimal.Decimal("7.514"), decimal.Decimal("7.51")),
        (decimal.Decimal("7.515"), decimal.Decimal("7.52")),
        (decimal.Decimal("7.525"), decimal.Decimal("7.53")),
        (decimal.Decimal("-7.504"), decimal.Decimal("-7.50")),
        (decimal.Decimal("-7.505"), decimal.Decimal("-7.51")),
        (decimal.Decimal("-7.515"), decimal.Decimal("-7.52")),
        (decimal.Decimal(0), decimal.Decimal("0")),
    ],
)
def test_round_number(number, expected):
    assert round_number(number) == expected
