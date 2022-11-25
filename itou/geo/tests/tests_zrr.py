from django.test import TestCase

from itou.geo.enums import ZRRStatus
from itou.geo.factories import ZRRFactory


class ZRRModelTest(TestCase):
    def setUp(self) -> None:
        self.in_zrr = ZRRFactory(in_zrr=True)
        self.not_in_zrr = ZRRFactory(not_in_zrr=True)
        self.partially_in_zrr = ZRRFactory(partially_in_zrr=True)

    def test_factory_traits(self):
        status = ZRRFactory(in_zrr=True).status

        self.assertIs(ZRRStatus.IN_ZRR, status)

        status = ZRRFactory(not_in_zrr=True).status

        self.assertIs(ZRRStatus.NOT_IN_ZRR, status)

        status = ZRRFactory(partially_in_zrr=True).status

        self.assertIs(ZRRStatus.PARTIALLY_IN_ZRR, status)
