from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation, Rome
from itou.utils.test import TestCase


class FixturesTest(TestCase):
    def test_create_test_romes_and_appellations(self):
        create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
        assert Rome.objects.count() == 2
        assert Appellation.objects.count() == 4
        assert Appellation.objects.filter(rome_id="M1805").count() == 2
        assert Appellation.objects.filter(rome_id="N1101").count() == 2
