import decimal


def round_number(number: decimal.Decimal) -> decimal.Decimal:
    return number.quantize(decimal.Decimal("0.01"), decimal.ROUND_HALF_UP)
