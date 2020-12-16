from django.test import TestCase
from itou.asp.models import LaneType, find_lane_type_aliases


class LaneTypeTest(TestCase):

    def test_aliases(self):
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grand rue"))
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grande-rue"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("R"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("r"))
        self.assertIsNone(find_lane_type_aliases("XXX"))


class LaneExtensionTest(TestCase):
    pass
