from itou.geo.enums import ZRRStatus
from itou.geo.factories import ZRRFactory
from itou.geo.models import ZRR
from itou.utils.test import TestCase


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

    def test_queryset(self):
        self.assertEqual(3, ZRR.objects.count())
        self.assertIn(self.in_zrr, ZRR.objects.in_zrr())
        self.assertIn(self.not_in_zrr, ZRR.objects.not_in_zrr())
        self.assertIn(self.partially_in_zrr, ZRR.objects.partially_in_zrr())

    def test_in_zrr_classmethod(self):
        self.assertTrue(ZRR.in_zrr(self.in_zrr.insee_code))
        self.assertFalse(ZRR.in_zrr(self.not_in_zrr.insee_code))
        self.assertFalse(ZRR.in_zrr(self.partially_in_zrr.insee_code))

    def test_partially_in_zrr_classmethod(self):
        self.assertFalse(ZRR.partially_in_zrr(self.in_zrr.insee_code))
        self.assertFalse(ZRR.partially_in_zrr(self.not_in_zrr.insee_code))
        self.assertTrue(ZRR.partially_in_zrr(self.partially_in_zrr.insee_code))
