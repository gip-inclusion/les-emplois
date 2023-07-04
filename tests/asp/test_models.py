from unittest import mock

from itou.asp.models import LaneExtension, LaneType, find_lane_type_aliases
from itou.common_apps.address.format import format_address
from itou.users.factories import JobSeekerFactory, JobSeekerWithAddressFactory
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, RESULTS_BY_ADDRESS
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK
from tests.utils.test import TestCase


def _users_with_mock_address(idx):
    address = BAN_GEOCODING_API_RESULTS_MOCK[idx]
    return JobSeekerWithAddressFactory(
        address_line_1=address.get("address_line_1"),
        post_code=address.get("post_code"),
    )


def mock_get_geocoding_data(address, post_code=None, limit=1):
    return RESULTS_BY_ADDRESS.get(address)


@mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
class FormatASPBadAdresses(TestCase):
    def test_not_existing_address(self, _mock):
        job_seeker = JobSeekerFactory(
            address_line_1="9, avenue de Huet", post_code="32531", city="MalletVille", department="32"
        )
        result, error = format_address(job_seeker)
        assert not result
        assert "Erreur de geocoding, impossible d'obtenir un résultat" in error


@mock.patch(
    "itou.common_apps.address.format.get_geocoding_data",
    side_effect=mock_get_geocoding_data,
)
class FormatASPAdresses(TestCase):
    def test_empty(self, _mock):
        result, error = format_address({})
        assert not result
        assert error == "Impossible de transformer cet objet en adresse HEXA"

    def test_none(self, _mock):
        result, error = format_address(None)
        assert not result
        assert error == "Impossible de transformer cet objet en adresse HEXA"

    def test_sanity(self, _):
        """
        Sanity check:
        every mock entries must be parseable and result must be valid
        """
        for idx, _elt in enumerate(RESULTS_BY_ADDRESS):
            user = _users_with_mock_address(idx)
            result, error = format_address(user)
            assert error is None
            assert result is not None

    def test_asp_addresses(self, _):
        """
        Test some of the most common address format
        Complete if needed.
        """
        user = _users_with_mock_address(0)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.RUE.name
        assert result.get("number") == "37"

        user = _users_with_mock_address(1)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.RTE.name
        assert result.get("number") == "382"

        user = _users_with_mock_address(2)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.RUE.name
        assert result.get("number") == "5"

        user = _users_with_mock_address(3)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.AV.name
        assert result.get("number") == "35"

        user = _users_with_mock_address(4)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.BD.name
        assert result.get("number") == "67"

        user = _users_with_mock_address(5)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.PL.name
        assert result.get("number") == "2"

        user = _users_with_mock_address(6)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.CITE.name

        user = _users_with_mock_address(7)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.CHEM.name
        assert result.get("number") == "261"

        user = _users_with_mock_address(8)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.LD.name

        user = _users_with_mock_address(9)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.PAS.name
        assert result.get("number") == "1"

        user = _users_with_mock_address(10)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.SQ.name
        assert result.get("number") == "2"

        user = _users_with_mock_address(11)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.HAM.name

        user = _users_with_mock_address(12)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.QUAR.name
        assert result.get("number") == "16"

        user = _users_with_mock_address(13)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.RES.name
        assert result.get("number") == "1"

        user = _users_with_mock_address(14)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.VOIE.name
        assert result.get("number") == "172"

        user = _users_with_mock_address(15)
        result, error = format_address(user)
        assert error is None
        assert result.get("lane_type") == LaneType.ALL.name
        assert result.get("number") == "3"


class LaneTypeTest(TestCase):
    def test_aliases(self):
        """
        Test some variants / alternatives used by api.geo.gouv.fr for lane types
        """
        assert LaneType.GR == find_lane_type_aliases("grand rue")
        assert LaneType.GR == find_lane_type_aliases("grande-rue")
        assert None is None, find_lane_type_aliases("grande'rue")
        assert LaneType.RUE == find_lane_type_aliases("R")
        assert LaneType.RUE == find_lane_type_aliases("r")
        assert LaneType.LD == find_lane_type_aliases("lieu dit")
        assert LaneType.LD == find_lane_type_aliases("lieu-dit")
        assert find_lane_type_aliases("XXX") is None


@mock.patch(
    "itou.common_apps.address.format.get_geocoding_data",
    side_effect=mock_get_geocoding_data,
)
class LaneExtensionTest(TestCase):
    def test_standard_extension(self, _):
        """
        Check if lane extension is included in ASP ref file
        """
        user = _users_with_mock_address(0)
        result, _error = format_address(user)
        assert result.get("std_extension") == LaneExtension.B.name

        user = _users_with_mock_address(16)
        result, _error = format_address(user)
        assert result.get("std_extension") == LaneExtension.T.name

    def test_non_standard_extension(self, _):
        """
        Non-standard extension, i.e. not in ASP ref file
        """
        user = _users_with_mock_address(17)
        result, _error = format_address(user)
        assert result.get("non_std_extension") == "G"
        assert result.get("std_extension") is None
