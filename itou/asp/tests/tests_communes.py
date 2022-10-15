import datetime as dt

from django.test import TestCase

from itou.asp.models import Commune


class _CommuneTest(TestCase):
    # Test fixture(s) to be checked
    fixtures = ["test_asp_INSEE_communes_factory.json"]


class CommunesFixtureTest(_CommuneTest):

    # INSEE commune with a single entry (1 history entry)
    _CODES_WITHOUT_HISTORY = ["97108", "13200"]
    ## Total number of entries in the file
    _NUMBER_OF_ENTRIES = 50
    # No commune registered before this date (end_date)
    _PERIOD_MIN_DATE = dt.date(1900, 1, 1)

    def test_small_test_fixture_structure(self):
        commune_set = Commune.objects.all()

        # Smoke tests, sort of
        # Will enforce checking structure if any update of test fixtures occurs
        # Reminder: these are referential, read-only, *external* data supplied by ASP
        self.assertEqual(commune_set.count(), self._NUMBER_OF_ENTRIES)

    def test_communes_with_history(self):
        codes_with_history = Commune.objects.exclude(code__in=self._CODES_WITHOUT_HISTORY).values_list(
            "code", flat=True
        )

        for code in codes_with_history:
            with self.subTest(code=code, msg="INSEE code without history"):
                # 2 entries for a code with history:
                communes = Commune.objects.filter(code=code)

                self.assertEqual(2, communes.count())

    def test_communes_without_history(self):
        for code in self._CODES_WITHOUT_HISTORY:
            with self.subTest(code=code):
                # Will error if many entries
                commune = Commune.objects.get(code=code)

                self.assertIsNone(commune.end_date)

    def test_current_entries(self):
        communes = Commune.objects.filter(end_date__isnull=True)

        self.assertEqual(26, communes.count())

        for commune in communes:
            with self.subTest():
                self.assertIsNone(commune.end_date)

    def test_lowest_period_date(self):
        communes = Commune.objects.filter(start_date__lt=self._PERIOD_MIN_DATE)

        self.assertEqual(0, communes.count())


class CommuneModelTest(_CommuneTest):
    def test_by_insee_code(self):
        current_communes = Commune.objects.current()

        for commune in current_communes:
            with self.subTest():
                result = Commune.by_insee_code(commune.code)
                self.assertEqual(result.code, commune.code)
