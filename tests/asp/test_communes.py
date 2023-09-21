import datetime

from itou.asp.models import Commune
from tests.utils.test import TestCase


class CommunesFixtureTest(TestCase):
    # INSEE commune with a single entry (1 history entry)
    _CODES_WITHOUT_HISTORY = ["97108", "13200"]
    ## Total number of entries in the file
    _NUMBER_OF_ENTRIES = 50
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

        for code in codes_with_history:
            with self.subTest(code=code, msg="INSEE code without history"):
                # 2 entries for a code with history:
                communes = Commune.objects.filter(code=code)

                assert 2 == communes.count()

    def test_communes_without_history(self):
        for code in self._CODES_WITHOUT_HISTORY:
            with self.subTest(code=code):
                # Will error if many entries
                commune = Commune.objects.get(code=code)

                assert commune.end_date is None

    def test_current_entries(self):
        communes = Commune.objects.filter(end_date__isnull=True)

        assert 26 == communes.count()

        for commune in communes:
            with self.subTest():
                assert commune.end_date is None

    def test_lowest_period_date(self):
        communes = Commune.objects.filter(start_date__lt=self._PERIOD_MIN_DATE)

        assert 0 == communes.count()


class CommuneModelTest(TestCase):
    def test_by_insee_code(self):
        old_commune = Commune(
            code=99999,
            name="ENNUI-SUR-BLASÉ",
            start_date=datetime.datetime(1940, 1, 1),
            end_date=datetime.datetime(2021, 12, 31),
        )
        new_commune = Commune(code=99999, name="ENNUI-SUR-BLASÉ", start_date=datetime.datetime(2022, 1, 1))
        Commune.objects.bulk_create([old_commune, new_commune])

        result = Commune.by_insee_code(99999)
        assert new_commune == result

    def test_by_insee_code_and_period(self):
        old_commune = Commune(
            code=99999,
            name="ENNUI-SUR-BLASÉ",
            start_date=datetime.datetime(1940, 1, 1),
            end_date=datetime.datetime(2021, 12, 31),
        )
        new_commune = Commune(code=99999, name="ENNUI-SUR-BLASÉ", start_date=datetime.datetime(2022, 1, 1))
        Commune.objects.bulk_create([old_commune, new_commune])

        result = Commune.by_insee_code_and_period(99999, datetime.datetime(1988, 4, 28))
        assert old_commune == result

        result = Commune.by_insee_code_and_period(99999, datetime.datetime(2022, 11, 28))
        assert new_commune == result
