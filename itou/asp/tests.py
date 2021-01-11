from unittest import mock

from django.test import TestCase

from itou.asp.models import LaneExtension, LaneType, find_lane_type_aliases
from itou.users.factories import JobSeekerWithAddressFactory
from itou.utils.address.format import format_address
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, RESULTS_BY_ADDRESS


def _users_with_mock_address(idx):
    address = BAN_GEOCODING_API_RESULTS_MOCK[idx]
    return JobSeekerWithAddressFactory(
        address_line_1=address.get("address_line_1"), post_code=address.get("post_code"),
    )


def mock_get_geocoding_data(address, post_code, limit=1):
    return RESULTS_BY_ADDRESS.get(address)


class FormatASPAdresses(TestCase):
    def test_valid_types(self):
        """Check input validity for address parsing"""
        result, error = format_address({})
        self.assertFalse(result)
        self.assertTrue(error)
        result, error = format_address(None)
        self.assertFalse(result)
        self.assertTrue(error)
        result, error = format_address(JobSeekerWithAddressFactory())
        self.assertFalse(error)
        self.assertTrue(result)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data", side_effect=mock_get_geocoding_data,
    )
    def test_sanity(self, _):
        """
        Sanity check:
        every mock entries must be parseable and result must be valid
        """
        for idx, elt in enumerate(RESULTS_BY_ADDRESS):
            user = _users_with_mock_address(idx)
            result, error = format_address(user, strict=False)
            self.assertIsNone(error)
            self.assertIsNotNone(result)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data", side_effect=mock_get_geocoding_data,
    )
    def test_asp_addresses(self, _):
        """
        Test some of the most common address format
        Complete if needed.
        """
        user = _users_with_mock_address(0)
        # strict=False ensures that user factories will be accepted as input type
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.RUE.name)
        self.assertEquals(result.get("number"), "37")

        user = _users_with_mock_address(1)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.RTE.name)
        self.assertEquals(result.get("number"), "382")

        user = _users_with_mock_address(2)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.RUE.name)
        self.assertEquals(result.get("number"), "5")

        user = _users_with_mock_address(3)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.AV.name)
        self.assertEquals(result.get("number"), "35")

        user = _users_with_mock_address(4)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.BD.name)
        self.assertEquals(result.get("number"), "67")

        user = _users_with_mock_address(5)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.PL.name)
        self.assertEquals(result.get("number"), "2")

        user = _users_with_mock_address(6)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.CITE.name)

        user = _users_with_mock_address(7)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.CHEM.name)
        self.assertEquals(result.get("number"), "261")

        user = _users_with_mock_address(8)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.LD.name)

        user = _users_with_mock_address(9)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.PAS.name)
        self.assertEquals(result.get("number"), "1")

        user = _users_with_mock_address(10)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.SQ.name)
        self.assertEquals(result.get("number"), "2")

        user = _users_with_mock_address(11)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.HAM.name)

        user = _users_with_mock_address(12)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.QUAR.name)
        self.assertEquals(result.get("number"), "16")

        user = _users_with_mock_address(13)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.RES.name)
        self.assertEquals(result.get("number"), "1")

        user = _users_with_mock_address(14)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.VOIE.name)
        self.assertEquals(result.get("number"), "172")

        user = _users_with_mock_address(15)
        result, error = format_address(user, strict=False)
        self.assertIsNone(error)
        self.assertEquals(result.get("lane_type"), LaneType.ALL.name)
        self.assertEquals(result.get("number"), "3")


class LaneTypeTest(TestCase):
    def test_aliases(self):
        """Test some variants / alternatives used by api.geo.gouv.fr for lane types"""
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grand rue"))
        self.assertEquals(LaneType.GR, find_lane_type_aliases("grande-rue"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("R"))
        self.assertEquals(LaneType.RUE, find_lane_type_aliases("r"))
        self.assertEquals(LaneType.LD, find_lane_type_aliases("lieu dit"))
        self.assertIsNone(find_lane_type_aliases("XXX"))


class LaneExtensionTest(TestCase):
    @mock.patch(
        "itou.utils.address.format.get_geocoding_data", side_effect=mock_get_geocoding_data,
    )
    def test_standard_extension(self, _):
        """Check if lane extension is included in ASP ref file"""
        user = _users_with_mock_address(0)
        result, error = format_address(user, strict=False)
        self.assertEquals(result.get("std_extension"), LaneExtension.B.name)

        user = _users_with_mock_address(16)
        result, error = format_address(user, strict=False)
        self.assertEquals(result.get("std_extension"), LaneExtension.T.name)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data", side_effect=mock_get_geocoding_data,
    )
    def test_non_standard_extension(self, _):
        """Non-standard extension, i.e. not in ASP ref file"""
        user = _users_with_mock_address(17)
        result, error = format_address(user, strict=False)
        self.assertEquals(result.get("non_std_extension"), "G")
        self.assertIsNone(result.get("std_extension"))
