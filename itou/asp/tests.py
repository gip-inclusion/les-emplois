from django.test import TestCase

from unittest import mock
from itou.asp.models import LaneType, find_lane_type_aliases
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, random_result_mock
from itou.utils.address.format import format_address
from itou.users.factories import JobSeekerWithAddressFactory


class LaneTypeTest(TestCase):
    def test_aliases(self):
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grand rue"))
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grande-rue"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("R"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("r"))
        self.assertIsNone(find_lane_type_aliases("XXX"))


class LaneExtensionTest(TestCase):
    pass


class FormatASPAdresses(TestCase):

    def test_valid_types(self):
        result, error = format_address({})
        self.assertFalse(result)
        self.assertTrue(error)
        result, error = format_address(None)
        self.assertFalse(result)
        self.assertTrue(error)
        result, error = format_address(JobSeekerWithAddressFactory())

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=random_result_mock())
    def test_sample_types(self, mock_call_ban_geocoding_api):
        pass
        # result_address = format_address()
