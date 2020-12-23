from unittest import mock

from django.test import TestCase

from itou.asp.models import LaneExtension, LaneType, find_lane_type_aliases
from itou.users.factories import JobSeekerWithAddressFactory
from itou.utils.address.format import format_address
from itou.utils.mocks.address_format import result_at_index, result_for_address, results_by_address


class LaneTypeTest(TestCase):
    def test_aliases(self):
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grand rue"))
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grande-rue"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("R"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("r"))
        self.assertIsNone(find_lane_type_aliases("XXX"))


class LaneExtensionTest(TestCase):
    pass


def _users_with_mock_address(idx):
    address = result_at_index(idx)
    return JobSeekerWithAddressFactory(
        address_line_1=address.get("address_line_1"), post_code=address.get("post_code"),
    )


def mock_get_geocoding_data(address, post_code, limit=1):
    return result_for_address(address)


class FormatASPAdresses(TestCase):
    def test_valid_types(self):
        result, error = format_address({})
        self.assertFalse(result)
        self.assertTrue(error)
        result, error = format_address(None)
        self.assertFalse(result)
        self.assertTrue(error)
        result, error = format_address(JobSeekerWithAddressFactory())

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data", side_effect=mock_get_geocoding_data,
    )
    def test_sanity(self, mock):
        # Every mock entries must be parseable
        for idx, elt in enumerate(results_by_address()):
            user = _users_with_mock_address(idx)
            result, error = format_address(user, strict=False)
            self.assertIsNone(error)
            self.assertIsNotNone(result)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data", side_effect=mock_get_geocoding_data,
    )
    def test_asp_addresses(self, mock):
        user = _users_with_mock_address(0)
        # strict=False ensures that user factories will be accepted as input type
        result, error = format_address(user, strict=False)
        self.assertEquals(result.get("lane_type"), LaneType.RUE.name)
        self.assertEquals(result.get("number"), "37")
        self.assertEquals(result.get("std_extension"), LaneExtension.B.name)
        # TODO to be continued...
