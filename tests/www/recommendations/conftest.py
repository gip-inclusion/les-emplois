import pytest

from tests.prescribers.factories import PrescriberMembershipFactory


SAFIR = "99999"
OTHER_SAFIR = "11111"


@pytest.fixture(autouse=True)
def enabled_safir(settings):
    """Enable the recommendations feature for `SAFIR` across the whole app's tests."""
    settings.ENABLED_RECOMMENDATIONS_SAFIR_CODES = [SAFIR]


@pytest.fixture
def advisor():
    """A prescriber whose organization carries the SAFIR code we test against."""
    membership = PrescriberMembershipFactory(
        organization__france_travail=True,
        organization__code_safir_pole_emploi=SAFIR,
    )
    return membership.user, membership.organization


@pytest.fixture
def other_advisor():
    """A France Travail prescriber whose SAFIR code is NOT enabled for recommendations."""
    membership = PrescriberMembershipFactory(
        organization__france_travail=True,
        organization__code_safir_pole_emploi=OTHER_SAFIR,
    )
    return membership.user, membership.organization
