import datetime

import freezegun
import pytest

from itou.utils.date import get_human_readable_estimate, monday_of_the_week, nb_days_in_year


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


# get_human_readable_estimate uses Django's timeuntil by default which converts a timedelta into
# calendar units (years, months, ...) from current day.
# 730 absolute days is the default duration of a PASS IAE, but it doesn't always equal 2 calendar years:
# when the span includes a leap year, 730 days falls 1 day short.
@pytest.mark.parametrize(
    "frozen_date, expected_for_730_days",
    [
        ("2026-02-28", "Environ 2 ans"),
        ("2026-03-01", "Environ 1 an et 11 mois"),
    ],
)
def test_human_readable_estimate(frozen_date, expected_for_730_days):
    with freezegun.freeze_time(frozen_date):
        for delta, expected_display in [
            (datetime.timedelta(days=730), expected_for_730_days),
            (datetime.timedelta(days=729), "Environ 1 an et 11 mois"),
            (datetime.timedelta(days=375), "Environ 1 an"),
            (datetime.timedelta(days=238), "Environ 7 mois et 3 semaines"),
            (datetime.timedelta(days=161), "Environ 5 mois et 1 semaine"),
            (datetime.timedelta(days=123), "Environ 4 mois"),
            (datetime.timedelta(days=15), "2 semaines et 1 jour"),
            (datetime.timedelta(days=14), "2 semaines"),
            (datetime.timedelta(days=13), "1 semaine et 6 jours"),
            (datetime.timedelta(days=7), "1 semaine"),
            (datetime.timedelta(days=6), "6 jours"),
            (datetime.timedelta(days=1), "1 jour"),
        ]:
            assert get_human_readable_estimate(delta) == expected_display
