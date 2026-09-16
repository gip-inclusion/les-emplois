import base64
import datetime
import hashlib
import hmac
import json

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.users.models import ProSupportReport
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


WEBHOOK_SECRET = "the-signing-secret"


@pytest.fixture(autouse=True)
def webhook_secret(settings):
    settings.TALLY_PRO_SUPPORT_REPORT_WEBHOOK_SECRET = WEBHOOK_SECRET


def build_payload(job_seeker, company, author, submitted_at):
    return {
        "eventId": "1e7b4a4f-4e2a-4a3e-9d5a-1b2c3d4e5f60",
        "eventType": "FORM_RESPONSE",
        "createdAt": submitted_at.isoformat(),
        "data": {
            "responseId": "mVGEg3",
            "formId": "OD2YZR",
            "fields": [
                {
                    "key": "question_1",
                    "label": "Le salarié a-t-il déjà une solution identifiée ?",
                    "type": "MULTIPLE_CHOICE",
                    "value": "Oui",
                },
                {
                    "key": "question_2",
                    "label": "uidjobseeker",
                    "type": "HIDDEN_FIELDS",
                    "value": str(job_seeker.public_id),
                },
                {"key": "question_3", "label": "idcompany", "type": "HIDDEN_FIELDS", "value": str(company.pk)},
                {"key": "question_4", "label": "iduser", "type": "HIDDEN_FIELDS", "value": str(author.pk)},
            ],
        },
    }


def post_webhook(client, payload, *, secret=WEBHOOK_SECRET):
    body = json.dumps(payload).encode()
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return client.post(
        reverse("pro_support:webhook"),
        data=body,
        content_type="application/json",
        headers={"tally-signature": signature},
    )


@freeze_time("2026-01-15")
def test_webhook_records_the_report(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    job_seeker = JobSeekerAssignmentFactory(professional=membership.user, company=membership.company).job_seeker

    response = post_webhook(client, build_payload(job_seeker, membership.company, membership.user, timezone.now()))

    assert response.status_code == 200
    report = ProSupportReport.objects.get()
    assert report.job_seeker == job_seeker
    assert report.company == membership.company
    assert report.submitted_at == timezone.now()


@freeze_time("2026-01-15")
def test_webhook_keeps_the_most_recent_report(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    job_seeker = JobSeekerAssignmentFactory(professional=membership.user, company=membership.company).job_seeker
    other_membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    JobSeekerAssignmentFactory(
        job_seeker=job_seeker, professional=other_membership.user, company=other_membership.company
    )
    post_webhook(client, build_payload(job_seeker, membership.company, membership.user, timezone.now()))

    # A retry of an older report does not replace it.
    older = timezone.now() - datetime.timedelta(days=1)
    post_webhook(client, build_payload(job_seeker, other_membership.company, other_membership.user, older))
    report = ProSupportReport.objects.get()
    assert report.company == membership.company
    assert report.submitted_at == timezone.now()

    newer = timezone.now() + datetime.timedelta(days=1)
    post_webhook(client, build_payload(job_seeker, other_membership.company, other_membership.user, newer))
    report = ProSupportReport.objects.get()
    assert report.company == other_membership.company
    assert report.submitted_at == newer


def test_webhook_without_a_valid_signature(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    job_seeker = JobSeekerAssignmentFactory(professional=membership.user, company=membership.company).job_seeker
    payload = build_payload(job_seeker, membership.company, membership.user, timezone.now())

    response = post_webhook(client, payload, secret="another-secret")

    assert response.status_code == 401
    assert not ProSupportReport.objects.exists()


def test_webhook_when_the_form_is_not_configured(client, settings):
    settings.TALLY_PRO_SUPPORT_REPORT_WEBHOOK_SECRET = None
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    job_seeker = JobSeekerAssignmentFactory(professional=membership.user, company=membership.company).job_seeker

    response = client.post(reverse("pro_support:webhook"), data={})

    assert response.status_code == 404
    assert not ProSupportReport.objects.filter(job_seeker=job_seeker).exists()


@pytest.mark.parametrize(
    "tampered_field",
    ["uidjobseeker", "idcompany", "iduser"],
)
def test_webhook_with_tampered_identifiers(client, tampered_field):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    job_seeker = JobSeekerAssignmentFactory(professional=membership.user, company=membership.company).job_seeker
    payload = build_payload(job_seeker, membership.company, membership.user, timezone.now())
    # The employer could edit the link before submitting the form.
    tampered_values = {
        "uidjobseeker": str(JobSeekerFactory().public_id),
        "idcompany": str(CompanyFactory(subject_to_iae_rules=True).pk),
        "iduser": str(CompanyMembershipFactory().user.pk),
    }
    for field in payload["data"]["fields"]:
        if field["label"] == tampered_field:
            field["value"] = tampered_values[tampered_field]

    response = post_webhook(client, payload)

    assert response.status_code == 400
    assert not ProSupportReport.objects.exists()
