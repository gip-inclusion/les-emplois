import datetime
from collections import Counter

import pytest
from django.utils import timezone

from itou.asp.models import Commune


class TestCommunesFixture:
    # INSEE commune with a single entry (1 history entry)
    _CODES_WITHOUT_HISTORY = ["97108", "13200", "97801"]
    ## Total number of entries in the file
    _NUMBER_OF_ENTRIES = 53
    # No commune registered before this date (end_date)
    _PERIOD_MIN_DATE = datetime.date(1900, 1, 1)

    def test_small_test_fixture_structure(self):
        commune_set = Commune.objects.all()

        # Smoke tests, sort of
        # Will enforce checking structure if any update of test fixtures occurs
        # Reminder: these are referential, read-only, *external* data supplied by ASP
        assert commune_set.count() == self._NUMBER_OF_ENTRIES

    def test_communes_with_history(self):
        codes_with_history = Commune.objects.exclude(code__in=self._CODES_WITHOUT_HISTORY).values_list(
            "code", flat=True
        )
        # All code are there twice
        commune_per_code = Counter(codes_with_history)
        assert commune_per_code == {code: 2 for code in set(codes_with_history)}

    def test_communes_without_history(self, subtests):
        for code in self._CODES_WITHOUT_HISTORY:
            with subtests.test(code=code):
                # Will error if many entries
                commune = Commune.objects.get(code=code)
                assert commune.end_date is None

    def test_current_entries(self):
        communes = Commune.objects.filter(end_date__isnull=True)
        assert 28 == communes.count()

    def test_lowest_period_date(self):
        communes = Commune.objects.filter(start_date__lt=self._PERIOD_MIN_DATE)
        assert 0 == communes.count()


class TestCommuneModel:
    def test_by_insee_code(self):
        old_commune = Commune(
            code=99999,
            name="ENNUI-SUR-BLASÉ",
            start_date=datetime.date(1940, 1, 1),
            end_date=datetime.date(2021, 12, 31),
        )
        new_commune = Commune(code=99999, name="ENNUI-SUR-BLASÉ", start_date=datetime.date(2022, 1, 1))
        Commune.objects.bulk_create([old_commune, new_commune])

        result = Commune.objects.by_insee_code(99999)
        assert new_commune == result

    def test_by_insee_code_and_period(self):
        old_commune = Commune(
            code=99999,
            name="ENNUI-SUR-BLASÉ",
            start_date=datetime.date(1940, 1, 1),
            end_date=datetime.date(2021, 12, 31),
        )
        new_commune = Commune(code=99999, name="ENNUI-SUR-BLASÉ", start_date=datetime.date(2022, 1, 1))
        Commune.objects.bulk_create([old_commune, new_commune])

        for period in [old_commune.start_date, datetime.date(1988, 4, 28), old_commune.end_date]:
            assert Commune.objects.by_insee_code_and_period(99999, period) == old_commune

        for period in [new_commune.start_date, datetime.date(2022, 11, 28), timezone.localdate()]:
            assert Commune.objects.by_insee_code_and_period(99999, period) == new_commune


@pytest.mark.parametrize(
    "insee_code,expected",
    [
        ("13150", "013"),  # Tarascon dans les Bouches-du-Rhône
        ("32389", "032"),  # Saint-Martin dans le Gers
        ("97416", "974"),  # Saint-Pierre à La Réunion
        ("97502", "975"),  # Saint-Pierre à Saint-Pierre-et-Miquelon
        ("97127", "971"),  # Saint-Martin en Guadeloupe
    ],
)
def test_department_code(insee_code, expected):
    commune = Commune(code=insee_code)
    assert commune.department_code == expected


def test_manager():
    Commune.objects.create(code="99999", start_date=datetime.date.min, name="Troufignoule-les-Oies", ignore=True)
    assert Commune.objects.filter(code="99999").count() == 0
    assert Commune.unfiltered_objects.filter(code="99999").count() == 1
