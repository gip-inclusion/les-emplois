from itou.geo.enums import ZRRStatus
from itou.geo.factories import ZRRFactory
from itou.geo.models import ZRR
from itou.utils.test import TestCase


class ZRRModelTest(TestCase):
    def test_factory_traits(self):
        status = ZRRFactory(in_zrr=True).status

        self.assertIs(ZRRStatus.IN_ZRR, status)

        status = ZRRFactory(not_in_zrr=True).status

        self.assertIs(ZRRStatus.NOT_IN_ZRR, status)

        status = ZRRFactory(partially_in_zrr=True).status

        self.assertIs(ZRRStatus.PARTIALLY_IN_ZRR, status)

    def test_queryset(self):
        in_zrr = ZRRFactory(in_zrr=True)
        not_in_zrr = ZRRFactory(not_in_zrr=True)
        partially_in_zrr = ZRRFactory(partially_in_zrr=True)

        self.assertEqual(3, ZRR.objects.count())
        self.assertIn(in_zrr, ZRR.objects.in_zrr())
        self.assertIn(not_in_zrr, ZRR.objects.not_in_zrr())
        self.assertIn(partially_in_zrr, ZRR.objects.partially_in_zrr())
