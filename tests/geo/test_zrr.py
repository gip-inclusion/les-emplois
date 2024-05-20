from itou.geo.enums import ZRRStatus
from tests.geo.factories import ZRRFactory
from tests.utils.test import TestCase


class ZRRModelTest(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.in_zrr = ZRRFactory(in_zrr=True)
        self.not_in_zrr = ZRRFactory(not_in_zrr=True)
        self.partially_in_zrr = ZRRFactory(partially_in_zrr=True)

    def test_factory_traits(self):
        status = ZRRFactory(in_zrr=True).status

        assert ZRRStatus.IN_ZRR is status

        status = ZRRFactory(not_in_zrr=True).status

        assert ZRRStatus.NOT_IN_ZRR is status

        status = ZRRFactory(partially_in_zrr=True).status

        assert ZRRStatus.PARTIALLY_IN_ZRR is status
