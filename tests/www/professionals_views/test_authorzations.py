import datetime
import random
from functools import partial

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import parse_response_to_soup, pretty_indented


DENIED_INSTITUTION_KINDS = list(set(InstitutionKind) - {InstitutionKind.DDETS_IAE})
DENIED_PRESCRIBER_KINDS = list(set(PrescriberOrganizationKind) - {PrescriberOrganizationKind.DEPT})


class AuthorizationsTestMixin:
    # Return test organizations for allowed users member of an organization in the 01 department
    # each function should return 2 lists of prescriber organizations : [allowed] [not allowed]
    def get_dept_fixtures(self):
        displayed = [
            # An ODC in the same department
            PrescriberOrganizationFactory(
                name="ODC du 01",
                kind=PrescriberOrganizationKind.ODC,
                department="01",
                authorization_status=PrescriberAuthorizationStatus.VALIDATED,  # "Validée" badge
                authorization_updated_at=datetime.datetime(2026, 11, 20, 12, 33, tzinfo=datetime.UTC),
                created_by=ItouStaffFactory(),  # created by La plateforme
                city="Oyonnax",
            ),
            # A brsa approved org in the same department
            PrescriberOrganizationFactory(
                name="PLIE du 01",
                kind=PrescriberOrganizationKind.PLIE,
                is_brsa=True,
                department="01",
                authorization_status=PrescriberAuthorizationStatus.NOT_SET,  # "En attente" badge
                created_by=PrescriberFactory(for_snapshot=True),  # created by a pro
                city="Valserhône",
            ),
            # An other ODC in the same department with no creator
            PrescriberOrganizationFactory(
                name="autre ODC du 01",
                kind=PrescriberOrganizationKind.ODC,
                department="01",
                authorization_status=PrescriberAuthorizationStatus.VALIDATED,
                authorization_updated_at=datetime.datetime(202, 10, 2, 15, 12, tzinfo=datetime.UTC),
                created_by=None,  # no creator
                city="Ambérieu-en-Bugey",
            ),
        ]
        not_displayed = [
            # An ODC in another department
            PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.ODC, department="02"),
            # A BRSA org in another department
            PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.PLIE, is_brsa=True, department="02"),
            # Any other org without brsa in the same department
            PrescriberOrganizationFactory(
                kind=random.choice(
                    [kind for kind in PrescriberOrganizationKind if kind != PrescriberOrganizationKind.ODC]
                ),
                is_brsa=False,
                department="01",
            ),
        ]
        return displayed, not_displayed

    def get_ddets_iae_fixtures(self):
        displayed = [
            # two OHPD in the same department
            PrescriberOrganizationFactory(
                name="OHPD 1",
                kind=PrescriberOrganizationKind.OHPD,
                department="01",
                authorization_status=PrescriberAuthorizationStatus.VALIDATED,
                authorization_updated_at=datetime.datetime(2026, 11, 20, 12, 33, tzinfo=datetime.UTC),
                created_by=ItouStaffFactory(),  # created by La plateforme
                city="Oyonnax",
            ),
            PrescriberOrganizationFactory(
                name="OHPD 2",
                kind=PrescriberOrganizationKind.OHPD,
                department="01",
                authorization_status=PrescriberAuthorizationStatus.NOT_SET,  # "En attente" badge
                created_by=PrescriberFactory(for_snapshot=True),  # created by a pro
                city="Valserhône",
            ),
            PrescriberOrganizationFactory(
                name="OHPD 3",
                kind=PrescriberOrganizationKind.OHPD,
                department="01",
                authorization_status=PrescriberAuthorizationStatus.VALIDATED,
                authorization_updated_at=datetime.datetime(202, 10, 2, 15, 12, tzinfo=datetime.UTC),
                created_by=None,  # no creator
                city="Ambérieu-en-Bugey",
            ),
        ]
        not_displayed = [
            # An OHPD in another department
            PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.ODC, department="02"),
            # Any other org in the same department without brsa
            PrescriberOrganizationFactory(
                kind=random.choice(
                    [kind for kind in PrescriberOrganizationKind if kind != PrescriberOrganizationKind.OHPD]
                ),
                department="01",
            ),
        ]
        return displayed, not_displayed


class TestAuthorizationListView(AuthorizationsTestMixin):
    @pytest.mark.parametrize(
        "factory,has_access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__kind=PrescriberOrganizationKind.DEPT), True),
            (
                partial(PrescriberFactory, membership__organization__kind=random.choice(DENIED_PRESCRIBER_KINDS)),
                False,
            ),
            (EmployerFactory, False),
            [partial(LaborInspectorFactory, membership__institution__kind=InstitutionKind.DDETS_IAE), True],
            [
                partial(LaborInspectorFactory, membership__institution__kind=random.choice(DENIED_INSTITUTION_KINDS)),
                False,
            ],
        ],
        ids=[
            "job_seeker",
            "prescriber_DEPT",
            "prescriber_other_kind",
            "employer",
            "labor_inspector_DDETS_IAE",
            "labor_inspector_other_kind",
        ],
    )
    def test_permissions(self, client, factory, has_access):
        user = factory()
        client.force_login(user)
        url = reverse("professionals_views:authorizations_list")
        response = client.get(url)
        assert response.status_code == 200 if has_access else 403

        response = client.get(reverse("dashboard:index"))
        if has_access:
            assertContains(response, url)
        else:
            assertNotContains(response, url)

    def test_DEPT(self, client, snapshot):
        user = PrescriberFactory(
            membership__organization__kind=PrescriberOrganizationKind.DEPT,
            membership__organization__department="01",
        )
        self.get_dept_fixtures()
        client.force_login(user)

        response = client.get(reverse("professionals_views:authorizations_list"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_DDETS_IAE(self, client, snapshot):
        user = LaborInspectorFactory(
            membership__institution__kind=InstitutionKind.DDETS_IAE,
            membership__institution__department="01",
        )
        self.get_ddets_iae_fixtures()
        client.force_login(user)

        response = client.get(reverse("professionals_views:authorizations_list"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot
