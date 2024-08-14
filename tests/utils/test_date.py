import datetime

import freezegun

from itou.utils.date import monday_of_the_week


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
