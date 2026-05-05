import datetime

import freezegun
import pytest

from itou.utils.date import monday_of_the_week, nb_days_in_year


def test_monday_of_the_week_with_arguments():
    mondays = set()
    for day in range(1, 32):
        mondays.add(monday_of_the_week(datetime.datetime(2024, 8, day, tzinfo=datetime.UTC)))
    assert mondays == {
        datetime.date(2024, 7, 29),
        datetime.date(2024, 8, 5),
        datetime.date(2024, 8, 12),
        datetime.date(2024, 8, 19),
        datetime.date(2024, 8, 26),
    }


def test_monday_of_the_week_without_arguments():
    with freezegun.freeze_time(datetime.date(2024, 8, 1)):
        assert monday_of_the_week() == datetime.date(2024, 7, 29)


@pytest.mark.parametrize(
    "start, end, year, expected",
    [
        ("2023-01-01", "2023-03-31", 2023, 90),
        ("2023-01-01", "2023-03-31", 2024, 0),
        ("2022-01-01", "2023-03-31", 2023, 90),
        ("2022-01-02", "2023-01-31", 2023, 31),
        ("2023-10-01", "2024-03-31", 2023, 92),
        ("2023-10-02", "2024-01-31", 2023, 91),
        ("2023-02-14", "2023-05-13", 2023, 89),
        ("2023-06-14", "2023-09-12", 2023, 91),
        ("2023-06-14", "2023-06-14", 2023, 1),
    ],
)
def test_nb_days_in_year(start, end, year, expected):
    start = datetime.date.fromisoformat(start)
    end = datetime.date.fromisoformat(end)
    assert nb_days_in_year(start, end, year=year) == expected
