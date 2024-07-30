from itou.geo.enums import ZRRStatus
from tests.geo.factories import ZRRFactory


def test_factory_traits():
    assert ZRRFactory(in_zrr=True).status == ZRRStatus.IN_ZRR
    assert ZRRFactory(not_in_zrr=True).status == ZRRStatus.NOT_IN_ZRR
    assert ZRRFactory(partially_in_zrr=True).status == ZRRStatus.PARTIALLY_IN_ZRR
