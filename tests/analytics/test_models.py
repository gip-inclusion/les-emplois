from contextlib import nullcontext

import pytest
from django.forms import ValidationError

from itou.analytics.models import PERCENTAGE_DATUM, Datum, DatumCode


class TestDatumModel:
    @pytest.mark.parametrize("DatumCodeEnum", set(DatumCode) - set(PERCENTAGE_DATUM))
    def test_get_value_display_not_percentage(self, DatumCodeEnum):
        assert Datum(code=DatumCodeEnum, value=13).get_value_display() == 13

    @pytest.mark.parametrize("DatumCodeEnum", PERCENTAGE_DATUM)
    def test_get_value_display_percentage(self, DatumCodeEnum):
        assert Datum(code=DatumCodeEnum, value=1111).get_value_display() == 11.11

    @pytest.mark.parametrize(
        "value,expected",
        [
            (42.5, pytest.raises(ValidationError)),
            ("You shall not pass.", pytest.raises(ValidationError)),
            (42, nullcontext()),
        ],
    )
    def test_save_with_exception(self, value, expected):
        with expected as e:
            assert Datum(value=value).save() == e
