from functools import partial

import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertRedirects

from itou.eligibility.models.iae import EligibilityDiagnosis
from tests.approvals.factories import ApprovalFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup, pretty_indented


class TestUpdateEligibilityView:
    @pytest.mark.parametrize(
        "factory,status_code",
        [
            [partial(JobSeekerFactory, for_snapshot=True), 403],
            (partial(PrescriberFactory, membership__organization__authorized=True), 200),
            (partial(PrescriberFactory, membership__organization__authorized=False), 403),
            (PrescriberFactory, 403),
            (partial(EmployerFactory, with_company=True), 403),
            [partial(LaborInspectorFactory, membership=True), 403],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "prescriber_with_org",
            "prescriber_no_org",
            "employer",
            "labor_inspector",
        ],
    )
    def test_permissions(self, client, factory, status_code):
        user = factory()
        job_seeker = user if user.is_job_seeker else JobSeekerFactory()
        client.force_login(user)
        url = reverse(
            "eligibility_views:update",
            kwargs={"job_seeker_public_id": job_seeker.public_id},
            query={"back_url": reverse("job_seekers_views:list")},
        )
        response = client.get(url)
        assert response.status_code == status_code

    def test_standalone_no_valid_eligibility_diagnosis(self, client, snapshot):
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        job_seeker = JobSeekerFactory(for_snapshot=True)

        client.force_login(prescriber)

        # Without a eligibility diagnosis
        url = reverse(
            "eligibility_views:update",
            kwargs={"job_seeker_public_id": job_seeker.public_id},
            query={"back_url": reverse("job_seekers_views:list")},
        )
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot(name="0")

        # With an expired eligibility diagnosis
        IAEEligibilityDiagnosisFactory(job_seeker=job_seeker, from_prescriber=True, expired=True)
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot(name="0")

        response = client.post(url, {"level_1_1": True})
        assertRedirects(response, reverse("job_seekers_views:list"))

        diag = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker, for_siae=None)
        assert diag.is_valid is True
        assert diag.expires_at == timezone.localdate() + relativedelta(months=6)

    @freeze_time("2025-03-22")
    def test_standalone_valid_eligibility_diagnosis(self, client, snapshot):
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        job_seeker = JobSeekerFactory(for_snapshot=True)
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=job_seeker, from_prescriber=True, author_prescriber_organization__for_snapshot=True
        )

        client.force_login(prescriber)
        url = reverse(
            "eligibility_views:update",
            kwargs={"job_seeker_public_id": job_seeker.public_id},
            query={"back_url": reverse("job_seekers_views:list")},
        )
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

        # if "shrouded" is present then we don't update the eligibility diagnosis
        response = client.post(url, {"level_1_1": True, "shrouded": "whatever"})
        assertRedirects(response, reverse("job_seekers_views:list"))
        assert [eligibility_diagnosis] == list(
            EligibilityDiagnosis.objects.for_job_seeker_and_siae(job_seeker=eligibility_diagnosis.job_seeker)
        )

        # If "shrouded" is NOT present then we update the eligibility diagnosis
        response = client.post(url, {"level_1_1": True})
        assertRedirects(response, reverse("job_seekers_views:list"))
        new_eligibility_diagnosis = (
            EligibilityDiagnosis.objects.for_job_seeker_and_siae(job_seeker=eligibility_diagnosis.job_seeker)
            .order_by()
            .last()
        )
        assert new_eligibility_diagnosis != eligibility_diagnosis
        assert new_eligibility_diagnosis.author == prescriber

    def test_valid_approval(self, client):
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        job_seeker = JobSeekerFactory(for_snapshot=True)
        ApprovalFactory(user=job_seeker)

        client.force_login(prescriber)
        url = reverse(
            "eligibility_views:update",
            kwargs={"job_seeker_public_id": job_seeker.public_id},
            query={"back_url": reverse("job_seekers_views:list")},
        )
        response = client.get(url)
        assertRedirects(response, reverse("job_seekers_views:list"))
