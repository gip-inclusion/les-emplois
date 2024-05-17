import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNumQueries

from itou.job_applications.enums import JobApplicationState
from itou.www.itou_staff_views.forms import DEPARTMENTS_CHOICES
from tests.approvals.factories import ApprovalFactory, ProlongationFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


class TestExportJobApplications:
    @pytest.mark.parametrize(
        "factory,factory_kwargs,expected_status",
        [
            (JobSeekerFactory, {}, 404),
            (EmployerFactory, {"with_company": True}, 404),
            (PrescriberFactory, {}, 404),
            (LaborInspectorFactory, {"membership": True}, 404),
            (ItouStaffFactory, {}, 404),
            (ItouStaffFactory, {"is_superuser": True}, 200),
        ],
    )
    def test_requires_superuser(self, client, factory, factory_kwargs, expected_status):
        user = factory(**factory_kwargs)
        client.force_login(user)
        response = client.get(reverse("itou_staff_views:export_job_applications_unknown_to_ft"))
        assert response.status_code == expected_status

    @pytest.mark.parametrize(
        "start,end,expected_queries",
        [
            pytest.param("2024-05-09", "2024-05-09", 5, id="before"),
            pytest.param("2024-05-10", "2024-05-10", 10, id="contains"),
            pytest.param("2024-05-11", "2024-05-11", 5, id="after"),
        ],
    )
    def test_export(self, client, start, end, expected_queries, snapshot):
        client.force_login(ItouStaffFactory(is_superuser=True))
        siae = CompanyFactory(for_snapshot=True, with_membership=True, siret="32112345600020", naf="1234Z")
        with freeze_time("2024-05-10T11:11:11+02:00"):
            job_seeker = JobSeekerFactory(
                for_snapshot=True,
                jobseeker_profile__pe_last_certification_attempt_at=timezone.now(),
                jobseeker_profile__hexa_post_code="35000",
            )
            eligibility_diag = EligibilityDiagnosisFactory(
                job_seeker=job_seeker,
                author_prescriber_organization__siret="12345678900012",
            )
            job_app = JobApplicationFactory(
                for_snapshot=True,
                job_seeker=job_seeker,
                to_company=siae,
                state=JobApplicationState.ACCEPTED,
                eligibility_diagnosis=eligibility_diag,
            )
            approval = ApprovalFactory(
                user=job_seeker,
                eligibility_diagnosis=eligibility_diag,
                number="XXXXX1234567",
            )
            job_app.approval = approval
            job_app.save()
            ProlongationFactory(
                for_snapshot=True,
                validated_by=PrescriberFactory(membership__organization__is_authorized=True),
                declared_by_siae=siae,
                approval=approval,
            )
        with (
            freeze_time("2024-05-17T11:11:11+02:00"),
            # 1. django session
            # 2. active user
            # 3. SAVEPOINT (enter view)
            # 4. RELEASE (exit view)
            # 5. SELECT job apps
            # 6. prefetch selected jobs
            # 7. prefetch administrative criteria
            # 8. prefetch eligibility diagnosis author prescriber organization
            # 9. prefetch prolongation
            # 10. prefetch suspension
            assertNumQueries(expected_queries),
        ):
            response = client.post(
                reverse("itou_staff_views:export_job_applications_unknown_to_ft"),
                {
                    "date_joined_from": start,
                    "date_joined_to": end,
                    "departments": DEPARTMENTS_CHOICES,
                },
            )
            assert response.status_code == 200
            assert response["Content-Disposition"] == (
                "attachment; "
                'filename="candidats_emplois_inclusion_multiple_departements_non_certifies_2024-05-17_11-11-11.csv"'
            )
            assert b"".join(response.streaming_content).decode() == snapshot

    def test_export_today(self, client):
        client.force_login(ItouStaffFactory(is_superuser=True))
        with freeze_time("2024-05-22T11:11:11+02:00"):
            response = client.post(
                reverse("itou_staff_views:export_job_applications_unknown_to_ft"),
                {
                    "date_joined_from": datetime.date.min.isoformat(),
                    "date_joined_to": timezone.localdate(),
                    "departments": DEPARTMENTS_CHOICES,
                },
            )
        print(response.content.decode())
        assertContains(
            response,
            '<div class="invalid-feedback">Assurez-vous que cette valeur est inférieure ou égale à 2024-05-21.</div>',
        )
