from datetime import date
from functools import partial

import pytest
from freezegun import freeze_time

from itou.communications.dispatch import EmailNotification
from itou.communications.dispatch.utils import ProfessionalNotification
from itou.companies.enums import CompanyKind
from itou.companies.notifications import (
    EndOfContractMonthlyRecapForEmployerNotification,
    PrescriberEndOfJourneyNotificationMixin,
)
from itou.prescribers.enums import PrescriberAuthorizationStatus
from tests.companies.factories import CompanyFactory, ContractFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import ProfessionalFactory


# No end of journey notification for prescribers yet.
class PrescriberNotification(PrescriberEndOfJourneyNotificationMixin, ProfessionalNotification, EmailNotification):
    pass


class TestEndOfJourneyNotificationMixin:
    @pytest.mark.parametrize(
        "notification_class, structure_factory, expected",
        [
            pytest.param(
                EndOfContractMonthlyRecapForEmployerNotification,
                partial(CompanyFactory, kind=CompanyKind.ACI),
                True,
                id="siae",
            ),
            pytest.param(
                EndOfContractMonthlyRecapForEmployerNotification,
                partial(CompanyFactory, kind=CompanyKind.GEIQ),
                False,
                id="non_siae",
            ),
            pytest.param(
                EndOfContractMonthlyRecapForEmployerNotification,
                PrescriberOrganizationFactory,
                False,
                id="siae_for_prescriber",
            ),
            pytest.param(
                EndOfContractMonthlyRecapForEmployerNotification, lambda: None, False, id="siae_without_structure"
            ),
            pytest.param(
                PrescriberNotification,
                partial(PrescriberOrganizationFactory, authorized=True),
                True,
                id="authorized_prescriber",
            ),
            pytest.param(
                PrescriberNotification,
                partial(
                    PrescriberOrganizationFactory, authorization_status=PrescriberAuthorizationStatus.NOT_REQUIRED
                ),
                False,
                id="unauthorized_prescriber",
            ),
            pytest.param(
                PrescriberNotification, partial(CompanyFactory, kind=CompanyKind.ACI), False, id="prescriber_for_siae"
            ),
            pytest.param(PrescriberNotification, lambda: None, False, id="prescriber_without_structure"),
        ],
    )
    def test_is_applicable(self, notification_class, structure_factory, expected):
        assert bool(notification_class(ProfessionalFactory(), structure_factory()).is_applicable()) is expected


class TestEndOfContractMonthlyRecapForEmployerNotification:
    @freeze_time("2026-11-10")
    @pytest.mark.parametrize(
        "last_month_count, this_month_count, expected_last_month_count, expected_this_month_count",
        [
            pytest.param(3, 4, 3, 4, id="all_contracts"),
            pytest.param(8, 8, 5, 5, id="half_for_each_group"),
            pytest.param(8, 2, 8, 2, id="last_month_contracts_take_free_places"),
            pytest.param(2, 8, 2, 8, id="this_month_contracts_take_free_places"),
            pytest.param(0, 12, 0, 10, id="this_month_contracts_only"),
        ],
    )
    def test_max_contracts(
        self, last_month_count, this_month_count, expected_last_month_count, expected_this_month_count
    ):
        last_month_contracts = ContractFactory.build_batch(last_month_count, end_date=date(2026, 10, 20))
        this_month_contracts = ContractFactory.build_batch(this_month_count, end_date=date(2026, 11, 20))
        notification = EndOfContractMonthlyRecapForEmployerNotification(
            ProfessionalFactory.build(),
            CompanyFactory.build(),
            contracts=last_month_contracts + this_month_contracts,
        )

        context = notification.get_context()
        assert [line["contract"] for line in context["last_month_contract_lines"]] == last_month_contracts[
            :expected_last_month_count
        ]
        assert context["last_month_contracts_count"] == last_month_count
        assert [line["contract"] for line in context["this_month_contract_lines"]] == this_month_contracts[
            :expected_this_month_count
        ]
        assert context["this_month_contracts_count"] == this_month_count

    @freeze_time("2026-11-10")
    def test_one_contract(self):
        contract = ContractFactory(end_date=date(2026, 11, 20))
        email = EndOfContractMonthlyRecapForEmployerNotification(
            ProfessionalFactory(), contract.company, contracts=[contract]
        ).build()

        assert "Voici le salarié que vous accompagnez" in email.body
        assert (
            "Remplir son bilan d’accompagnement permet à son prescripteur de préparer la suite avec lui." in email.body
        )
        assert "**Contrat qui se termine ce mois-ci (1)**" in email.body
