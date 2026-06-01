from functools import partial

import pytest
from django.urls import reverse

from tests.users.factories import JobSeekerFactory, PrescriberFactory, random_pro_user_factory
from tests.utils.testing import parse_response_to_soup, pretty_indented
from tests.www.recommendations.factories import BeneficiaryFactory


class TestListView:
    @pytest.mark.parametrize(
        "factory,access",
        [
            [JobSeekerFactory, False],
            [partial(random_pro_user_factory, membership=True), False],
            [
                partial(
                    PrescriberFactory,
                    membership__organization__france_travail=True,
                    membership__organization__code_safir_pole_emploi="11111",
                ),
                False,
            ],
            [
                partial(
                    PrescriberFactory,
                    membership__organization__france_travail=True,
                    membership__organization__code_safir_pole_emploi="99999",
                ),
                True,
            ],
        ],
        ids=["job_seeker", "professional", "any_ft_prescriber", "authorized_ft_prescriber"],
    )
    def test_permission(self, client, settings, factory, access):
        settings.ENABLED_RECOMMENDATIONS_SAFIR_CODES = ["99999"]
        user = factory()
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"))
        if access:
            assert response.status_code == 200
        else:
            assert response.status_code == 403

    def test_view(self, client, settings, snapshot):
        safir_code = "99999"
        settings.ENABLED_RECOMMENDATIONS_SAFIR_CODES = [safir_code]
        user = PrescriberFactory(
            membership__organization__france_travail=True,
            membership__organization__code_safir_pole_emploi=safir_code,
        )
        client.force_login(user)

        # displayed beneficiary
        BeneficiaryFactory(
            first_name="John",
            last_name="Doe",
            referent_email=user.email,
            organization_safir=safir_code,
        )
        BeneficiaryFactory(referent_email=user.email, organization_safir="11111")  # Other safir code
        BeneficiaryFactory(organization_safir=safir_code)  # Other referent email

        response = client.get(reverse("recommendations:beneficiary_list"))
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot
