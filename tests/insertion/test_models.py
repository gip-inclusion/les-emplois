import pytest

from tests.insertion.factories import StructureFactory


@pytest.mark.no_django_db
@pytest.mark.parametrize(
    "address_kwargs,expected",
    [
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "Bât. B",
                "post_code": "38110",
                "city": "La Tour du Pin",
            },
            "12 rue des terreaux, Bât. B, 38110 La Tour du Pin",
            id="complete_address",
        ),
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "",
                "post_code": "38110",
                "city": "La Tour du Pin",
            },
            "12 rue des terreaux, 38110 La Tour du Pin",
            id="without_address_line_2",
        ),
    ],
)
def test_address_on_one_line(address_kwargs, expected):
    structure = StructureFactory.build(**address_kwargs)
    assert structure.address_on_one_line == expected


@pytest.mark.no_django_db
@pytest.mark.parametrize(
    "address_kwargs",
    [
        pytest.param(
            {
                "address_line_1": "",
                "address_line_2": "Bât. B",
                "post_code": "38110",
                "city": "La Tour du Pin",
            },
            id="missing_address_line_1",
        ),
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "Bât. B",
                "post_code": "",
                "city": "La Tour du Pin",
            },
            id="missing_post_code",
        ),
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "Bât. B",
                "post_code": "38110",
                "city": "",
            },
            id="missing_city",
        ),
    ],
)
def test_address_on_one_line_incomplete_returns_none(address_kwargs):
    structure = StructureFactory.build(**address_kwargs)
    assert structure.address_on_one_line is None
