import datetime
from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.approvals.enums import Origin
from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models import AdministrativeCriteria
from itou.institutions.enums import InstitutionKind
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationQuerySet
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import (
    Calendar,
    CampaignAlreadyPopulatedException,
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
    Sanctions,
    create_campaigns_and_calendar,
    select_min_max_job_applications,
    validate_institution,
)
from itou.utils.models import InclusiveDateRange
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.files.factories import FileFactory
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionWith2MembershipFactory,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import JobSeekerFactory, PrescriberFactory


def create_batch_of_job_applications(company):
    start = timezone.localdate() - relativedelta(months=2)
    for _ in range(evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN):
        approval = ApprovalFactory(
            start_at=start,
            eligibility_diagnosis__author_kind=AuthorKind.EMPLOYER,
            eligibility_diagnosis__author_siae=company,
        )
        JobApplicationFactory.create(
            state=JobApplicationState.ACCEPTED,
            job_seeker=approval.user,
            eligibility_diagnosis=approval.eligibility_diagnosis,
            to_company=company,
            sender_company=company,
            hiring_start_at=start,
            approval=approval,
        )


class TestEvaluationCampaignMiscMethods:
    def test_select_min_max_job_applications(self):
        company = CompanyFactory()
        job_seeker = JobSeekerFactory()
        sender = PrescriberFactory()
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker)

        def create_job_apps(count):
            return JobApplicationFactory.create_batch(
                count,
                to_company=company,
                job_seeker=job_seeker,
                eligibility_diagnosis=eligibility_diagnosis,
                sender=sender,
            )

        # zero job application
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_company=company))
        assert isinstance(qs, JobApplicationQuerySet)
        assert 0 == qs.count()

        # one job applications made by SIAE
        [job_application] = create_job_apps(1)
        assert (
            job_application
            == select_min_max_job_applications(JobApplication.objects.filter(to_company=company)).first()
        )
        assert 1 == select_min_max_job_applications(JobApplication.objects.filter(to_company=company)).count()

        # under 10 job applications, 20% is below the minimum value of 2 -> select 2
        create_job_apps(5)
        assert (
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN
            == select_min_max_job_applications(JobApplication.objects.filter(to_company=company)).count()
        )

        # from 20 job applications to 100 we have the correct percentage
        create_job_apps(55)
        assert 12 == select_min_max_job_applications(JobApplication.objects.filter(to_company=company)).count()

        # Over 100, stop at the max number -> 20
        create_job_apps(50)
        assert (
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MAX
            == select_min_max_job_applications(JobApplication.objects.filter(to_company=company)).count()
        )


class TestEvaluationCampaignQuerySet:
    def test_for_institution(self):
        institution1 = InstitutionFactory(department="01")
        EvaluationCampaignFactory(institution=institution1)

        institution2 = InstitutionFactory(department="02")
        now = timezone.now()
        EvaluationCampaignFactory(
            institution=institution2,
            evaluated_period_start_at=now.date() - relativedelta(months=9),
            evaluated_period_end_at=now.date() - relativedelta(months=8),
        )
        EvaluationCampaignFactory(
            institution=institution2,
            evaluated_period_start_at=now.date() - relativedelta(months=7),
            evaluated_period_end_at=now.date() - relativedelta(months=6),
        )
        created_at_idx0 = EvaluationCampaign.objects.for_institution(institution2)[0].evaluated_period_end_at
        created_at_idx1 = EvaluationCampaign.objects.for_institution(institution2)[1].evaluated_period_end_at
        assert 3 == EvaluationCampaign.objects.all().count()
        assert 2 == EvaluationCampaign.objects.for_institution(institution2).count()
        assert created_at_idx0 > created_at_idx1

    def test_in_progress(self):
        institution = InstitutionFactory()
        assert 0 == EvaluationCampaign.objects.all().count()
        assert 0 == EvaluationCampaign.objects.in_progress().count()

        now = timezone.now()
        sometimeago = now - relativedelta(months=2)
        EvaluationCampaignFactory(
            institution=institution,
            ended_at=sometimeago,
        )
        EvaluationCampaignFactory(
            institution=institution,
        )
        assert 2 == EvaluationCampaign.objects.all().count()
        assert 1 == EvaluationCampaign.objects.in_progress().count()


@pytest.fixture
def campaign_eligible_job_app_objects():
    company = CompanyWith2MembershipsFactory(department="14")
    job_seeker = JobSeekerFactory()
    start = timezone.now() - relativedelta(months=2)
    approval = ApprovalFactory(user=job_seeker, start_at=start)
    diag = IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        author_kind=AuthorKind.EMPLOYER,
        author_siae=company,
        author=company.members.first(),
    )
    job_app = JobApplicationFactory(
        job_seeker=job_seeker,
        approval=approval,
        to_company=company,
        sender_company=company,
        eligibility_diagnosis=diag,
        hiring_start_at=start,
        state=JobApplicationState.ACCEPTED,
    )
    return {
        "approval": approval,
        "diag": diag,
        "job_app": job_app,
        "siae": company,
    }


class TestEvaluationCampaignManagerEligibleJobApplication:
    def test_eligible_job_application(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        job_app = campaign_eligible_job_app_objects["job_app"]
        assert [job_app] == list(evaluation_campaign.eligible_job_applications())

    def test_no_approval(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        job_app = campaign_eligible_job_app_objects["job_app"]
        job_app.approval = None
        job_app.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_outside_institution_department(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        siae = campaign_eligible_job_app_objects["siae"]
        siae.department = 12
        siae.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    @pytest.mark.parametrize(
        "kind", [k for k in CompanyKind if k not in evaluation_enums.EvaluationSiaesKind.Evaluable]
    )
    def test_siae_not_eligible_kind(self, kind, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        siae = campaign_eligible_job_app_objects["siae"]
        siae.kind = kind
        siae.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_job_application_not_accepted(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        job_app = campaign_eligible_job_app_objects["job_app"]
        job_app.state = JobApplicationState.REFUSED
        job_app.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_job_application_not_in_period(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        job_app = campaign_eligible_job_app_objects["job_app"]
        new_start = timezone.now() - relativedelta(months=10)
        job_app.hiring_start_at = new_start
        job_app.save(update_fields=["hiring_start_at"])
        job_app.approval.start_at = new_start
        job_app.approval.save(update_fields=["start_at"])
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_eligibility_diag_not_made_by_employer(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        diag = campaign_eligible_job_app_objects["diag"]
        diag.author_kind = AuthorKind.PRESCRIBER
        diag.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_eligibility_diag_made_by_another_siae(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        diag = campaign_eligible_job_app_objects["diag"]
        diag.author_siae = CompanyFactory()
        diag.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_approval_does_not_start_with_itou_prefix(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        approval = campaign_eligible_job_app_objects["approval"]
        approval.number = "0123456789"
        approval.origin = Origin.PE_APPROVAL
        approval.eligibility_diagnosis = None
        approval.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())


class TestEvaluationCampaignManager:
    def test_validate_institution(self, subtests):
        with pytest.raises(ValidationError):
            validate_institution(0)

        for kind in [k for k in InstitutionKind if k != InstitutionKind.DDETS_IAE]:
            with subtests.test(kind=kind.name):
                institution = InstitutionFactory(kind=kind)
                with pytest.raises(ValidationError):
                    validate_institution(institution.id)

    def test_clean(self):
        now = timezone.now()
        institution = InstitutionFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution)

        evaluation_campaign.evaluated_period_start_at = now.date()
        evaluation_campaign.evaluated_period_end_at = now.date()
        with pytest.raises(ValidationError):
            evaluation_campaign.clean()

        evaluation_campaign.evaluated_period_start_at = now.date()
        evaluation_campaign.evaluated_period_end_at = now.date() - relativedelta(months=6)
        with pytest.raises(ValidationError):
            evaluation_campaign.clean()

    def test_create_campaigns_and_calendar(self, subtests, django_capture_on_commit_callbacks):
        evaluated_period_start_at = timezone.now() - relativedelta(months=2)
        evaluated_period_end_at = timezone.now() - relativedelta(months=1)
        adversarial_stage_start = timezone.localdate() + relativedelta(months=1)

        # not DDETS IAE
        for kind in [k for k in InstitutionKind if k != InstitutionKind.DDETS_IAE]:
            with subtests.test(kind=kind.name):
                InstitutionFactory(kind=kind)
                with django_capture_on_commit_callbacks(execute=True):
                    assert 0 == create_campaigns_and_calendar(
                        evaluated_period_start_at, evaluated_period_end_at, adversarial_stage_start
                    )
                assert 0 == EvaluationCampaign.objects.all().count()
                assert 1 == Calendar.objects.all().count()
                assert len(mail.outbox) == 0

        # institution DDETS IAE
        InstitutionWith2MembershipFactory(kind=InstitutionKind.DDETS_IAE, department="O1")
        InstitutionWith2MembershipFactory(kind=InstitutionKind.DDETS_IAE, department="1O")
        with django_capture_on_commit_callbacks(execute=True):
            assert 2 == create_campaigns_and_calendar(
                evaluated_period_start_at, evaluated_period_end_at, adversarial_stage_start
            )
        assert 2 == EvaluationCampaign.objects.all().count()
        assert 1 == Calendar.objects.all().count()

        # An email should have been sent to the institution members.
        assert len(mail.outbox) == 2
        email = mail.outbox[0]
        assert len(email.to) == 2
        email = mail.outbox[1]
        assert len(email.to) == 2

    def test_create_campaigns_and_calendar_on_specific_DDETS_IAE(self):
        evaluated_period_start_at = timezone.now() - relativedelta(months=2)
        evaluated_period_end_at = timezone.now() - relativedelta(months=1)
        adversarial_stage_start = timezone.localdate() + relativedelta(months=1)
        institution_ids = [
            InstitutionWith2MembershipFactory(kind=InstitutionKind.DDETS_IAE, department="O1"),
            InstitutionWith2MembershipFactory(kind=InstitutionKind.DDETS_IAE, department="1O"),
        ]
        assert 1 == create_campaigns_and_calendar(
            evaluated_period_start_at,
            evaluated_period_end_at,
            adversarial_stage_start,
            institution_ids=[institution_ids[0].pk],
        )
        assert 1 == EvaluationCampaign.objects.all().count()

    def test_eligible_siaes(self):
        evaluation_campaign = EvaluationCampaignFactory()

        # company_1 got 1 job application
        company_1 = CompanyFactory(department="14")
        JobApplicationFactory(
            with_approval=True,
            to_company=company_1,
            sender_company=company_1,
            eligibility_diagnosis__author_kind=AuthorKind.EMPLOYER,
            eligibility_diagnosis__author_siae=company_1,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        # company_2 got 2 job applications
        company_2 = CompanyFactory(department="14")
        create_batch_of_job_applications(company_2)

        eligible_siaes_res = evaluation_campaign.eligible_siaes()
        assert 1 == eligible_siaes_res.count()
        assert {
            "to_company": company_2.id,
            "to_company_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
        } in eligible_siaes_res

        # adding 2 more job applications to company_2
        create_batch_of_job_applications(company_2)

        eligible_siaes_res = evaluation_campaign.eligible_siaes()
        assert 1 == eligible_siaes_res.count()
        assert {
            "to_company": company_2.id,
            "to_company_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN * 2,
        } in eligible_siaes_res

    def test_eligible_siae_approval_from_past_year(self):
        evaluation_campaign = EvaluationCampaignFactory(
            evaluated_period_start_at=datetime.date(2023, 1, 1),
            evaluated_period_end_at=datetime.date(2023, 12, 31),
        )
        company = CompanyFactory(department=evaluation_campaign.institution.department, with_membership=True)
        before_evaluated_period = datetime.date(2022, 4, 4)
        approval1 = ApprovalFactory(
            start_at=before_evaluated_period,  # Before evaluated period.
            eligibility_diagnosis__author_kind=AuthorKind.EMPLOYER,
            eligibility_diagnosis__author_siae=company,
        )
        job_app_approval1_args = {
            "state": JobApplicationState.ACCEPTED,
            "job_seeker": approval1.user,
            "eligibility_diagnosis": approval1.eligibility_diagnosis,
            "to_company": company,
            "approval": approval1,
        }
        JobApplicationFactory.create(**job_app_approval1_args, hiring_start_at=before_evaluated_period)
        # Should be ignored, it did not create the approval.
        JobApplicationFactory.create(
            **job_app_approval1_args,
            hiring_start_at=datetime.date(2023, 5, 6),  # Within evaluated period.
        )
        within_evaluated_period = datetime.date(2023, 2, 1)
        approval2 = ApprovalFactory(
            start_at=within_evaluated_period,
            eligibility_diagnosis__author_kind=AuthorKind.EMPLOYER,
            eligibility_diagnosis__author_siae=company,
        )
        JobApplicationFactory.create(
            state=JobApplicationState.ACCEPTED,
            job_seeker=approval2.user,
            eligibility_diagnosis=approval2.eligibility_diagnosis,
            to_company=company,
            approval=approval2,
            hiring_start_at=within_evaluated_period,
        )
        assert not evaluation_campaign.eligible_siaes()

    def test_number_of_siaes_to_select(self):
        evaluation_campaign = EvaluationCampaignFactory()
        assert 0 == evaluation_campaign.number_of_siaes_to_select()

        for _ in range(3):
            company = CompanyFactory(department="14")
            create_batch_of_job_applications(company)

        assert 1 == evaluation_campaign.number_of_siaes_to_select()

        for _ in range(3):
            company = CompanyFactory(department="14")
            create_batch_of_job_applications(company)

        assert 2 == evaluation_campaign.number_of_siaes_to_select()

    def test_eligible_siaes_under_ratio(self):
        evaluation_campaign = EvaluationCampaignFactory()

        for _ in range(6):
            company = CompanyFactory(department="14")
            create_batch_of_job_applications(company)

        assert 2 == evaluation_campaign.eligible_siaes_under_ratio().count()

    def test_populate(self, subtests):
        # integration tests
        evaluation_campaign = EvaluationCampaignFactory()
        company = CompanyFactory(department=evaluation_campaign.institution.department, with_membership=True)
        create_batch_of_job_applications(company)
        fake_now = timezone.now() - relativedelta(weeks=1)

        assert 0 == EvaluatedSiae.objects.all().count()
        assert 0 == EvaluatedJobApplication.objects.all().count()

        with assertNumQueries(
            1  # SAVEPOINT from transaction.atomic()
            + 1  # UPDATE SET percent_set_at
            + 1  # COUNT eligible job applications
            + 1  # SELECT to_company_id and job application count for SIAE with at least 2 auto-prescriptions.
            + 1  # SELECT SIAE details
            + 1  # INSERT EvaluatedSiae
            + 1  # COUNT eligible job applications
            + 1  # SELECT job applications to evaluate
            + 1  # INSERT EvaluatedJobApplication
            + 1  # SELECT SIAE convention
            + 1  # SELECT SIAE admin users
            + 1  # SELECT institution users
            + 1  # INSERT email for employer
            + 1  # INSERT email for institution user
            + 1  # RELEASE SAVEPOINT (end of transaction.atomic())
        ):
            evaluation_campaign.populate(fake_now)
        evaluation_campaign.refresh_from_db()

        assert fake_now == evaluation_campaign.percent_set_at
        assert fake_now == evaluation_campaign.evaluations_asked_at
        assert 1 == EvaluatedSiae.objects.all().count()
        assert 2 == EvaluatedJobApplication.objects.all().count()

        # check links between EvaluatedSiae and EvaluatedJobApplication
        evaluated_siae = EvaluatedSiae.objects.first()
        for evaluated_job_application in EvaluatedJobApplication.objects.all():
            with subtests.test(evaluated_job_application_pk=evaluated_job_application.pk):
                assert evaluated_siae == evaluated_job_application.evaluated_siae

        # retry on populated campaign
        with pytest.raises(CampaignAlreadyPopulatedException):
            evaluation_campaign.populate(fake_now)

    @freeze_time("2023-01-02 11:11:11")
    def test_transition_to_adversarial_phase(self, django_capture_on_commit_callbacks, snapshot):
        institution = InstitutionFactory(name="DDETS 1", department="01")
        ignored_siae = EvaluatedSiaeFactory(pk=1000, siae__pk=2000, evaluation_campaign__institution=institution)
        campaign = EvaluationCampaignFactory(institution=institution)
        # Did not select eligibility criteria to justify.
        evaluated_siae_no_response = EvaluatedSiaeFactory(
            pk=1001, evaluation_campaign=campaign, siae__name="Les grands jardins", siae__pk=2001
        )
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_no_response)
        evaluated_siae_no_docs = EvaluatedSiaeFactory(
            pk=1002, evaluation_campaign=campaign, siae__name="Les petits jardins", siae__pk=2002
        )
        evaluated_jobapp_no_docs = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_no_docs)
        EvaluatedAdministrativeCriteriaFactory(
            uploaded_at=timezone.now() - relativedelta(days=7),
            evaluated_job_application=evaluated_jobapp_no_docs,
            # default review_state is PENDING
        )
        evaluated_siae_submitted = EvaluatedSiaeFactory(
            pk=1003, evaluation_campaign=campaign, siae__name="Prim’vert", siae__pk=2003
        )
        evaluated_jobapp_submitted = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_submitted)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=6),
            evaluated_job_application=evaluated_jobapp_submitted,
            # default review_state is PENDING
        )
        accepted_ts = timezone.now() - relativedelta(days=1)
        evaluated_siae_accepted = EvaluatedSiaeFactory(
            pk=1004,
            evaluation_campaign=campaign,
            siae__name="Geo accepted",
            siae__pk=2004,
            reviewed_at=accepted_ts,
            final_reviewed_at=accepted_ts,
        )
        evaluated_jobapp_accepted = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_accepted)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=2),
            evaluated_job_application=evaluated_jobapp_accepted,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        refused_ts = timezone.now() - relativedelta(days=3)
        evaluated_siae_refused = EvaluatedSiaeFactory(
            pk=1005,
            evaluation_campaign=campaign,
            siae__name="Geo refused",
            siae__pk=2005,
            reviewed_at=refused_ts,
        )
        evaluated_jobapp_refused = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_refused)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=4),
            evaluated_job_application=evaluated_jobapp_refused,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )

        with django_capture_on_commit_callbacks(execute=True):
            campaign.transition_to_adversarial_phase()

        assert ignored_siae == EvaluatedSiae.objects.get(reviewed_at__isnull=True)

        # Transitioned to ACCEPTED, the DDETS IAE did not review the documents
        # submitted by SIAE before the transition.
        evaluated_siae_submitted.refresh_from_db()
        assert evaluated_siae_submitted.reviewed_at == datetime.datetime(2023, 1, 2, 11, 11, 11, tzinfo=datetime.UTC)
        assert evaluated_siae_submitted.final_reviewed_at == datetime.datetime(
            2023, 1, 2, 11, 11, 11, tzinfo=datetime.UTC
        )
        assert evaluated_siae_submitted.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

        evaluated_siae_accepted.refresh_from_db()
        assert evaluated_siae_accepted.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED
        assert evaluated_siae_accepted.reviewed_at == accepted_ts
        assert evaluated_siae_accepted.final_reviewed_at == accepted_ts

        evaluated_siae_refused.refresh_from_db()
        assert evaluated_siae_refused.state == evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE
        assert evaluated_siae_refused.reviewed_at == refused_ts
        assert evaluated_siae_refused.final_reviewed_at is None

        [
            siae_accepted_email,
            siae_refused_email,
            siae_no_response_email,
            siae_no_docs_email,
            siae_force_accepted,
            institution_email,
        ] = sorted(mail.outbox, key=lambda mail: mail.subject)
        assert (
            siae_refused_email.subject
            == f"[DEV] Résultat du contrôle - EI Geo refused ID-{evaluated_siae_refused.siae_id}"
        )
        assert siae_refused_email.body == snapshot(name="refused review email body")

        assert (
            siae_accepted_email.subject
            == f"[DEV] Résultat du contrôle - EI Geo accepted ID-{evaluated_siae_accepted.siae_id}"
        )
        assert siae_accepted_email.body == snapshot(name="accepted review email body")

        assert (
            siae_no_response_email.subject
            == f"[DEV] Résultat du contrôle - EI Les grands jardins ID-{evaluated_siae_no_response.siae_id}"
        )
        assert siae_no_response_email.body == snapshot(name="no response email body")

        assert (
            siae_no_docs_email.subject
            == f"[DEV] Résultat du contrôle - EI Les petits jardins ID-{evaluated_siae_no_docs.siae_id}"
        )
        assert siae_no_docs_email.body == snapshot(name="no docs email body")

        assert (
            siae_force_accepted.subject
            == f"[DEV] Résultat du contrôle - EI Prim’vert ID-{evaluated_siae_submitted.siae_id}"
        )
        assert siae_force_accepted.body == snapshot(name="force accepted email body")

        assert institution_email.subject == "[DEV] [Contrôle a posteriori] Passage en phase contradictoire"
        assert institution_email.body == snapshot(name="institution summary email body")

    @freeze_time("2023-01-02 11:11:11")
    def test_transition_to_adversarial_phase_forced_to_adversarial_stage(
        self, django_capture_on_commit_callbacks, snapshot
    ):
        campaign = EvaluationCampaignFactory(institution__name="DDETS 1")
        evaluated_siae_no_response = EvaluatedSiaeFactory(
            pk=1000,
            evaluation_campaign=campaign,
            siae__name="Les grands jardins",
            siae__pk=2000,
        )
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_no_response)

        with django_capture_on_commit_callbacks(execute=True):
            campaign.transition_to_adversarial_phase()

        evaluated_siae_no_response.refresh_from_db()
        assert evaluated_siae_no_response.reviewed_at == timezone.now()

        [siae_no_response_email, institution_email] = sorted(mail.outbox, key=lambda mail: mail.subject)
        assert (
            siae_no_response_email.subject
            == f"[DEV] Résultat du contrôle - EI Les grands jardins ID-{evaluated_siae_no_response.siae_id}"
        )
        assert siae_no_response_email.body == snapshot(name="no response email body")

        assert institution_email.subject == "[DEV] [Contrôle a posteriori] Passage en phase contradictoire"
        assert institution_email.body == snapshot(name="institution summary email body")

    @freeze_time("2023-01-02 11:11:11")
    def test_transition_to_adversarial_phase_force_accepted(self, django_capture_on_commit_callbacks, snapshot):
        campaign = EvaluationCampaignFactory(institution__name="DDETS 1")
        evaluated_siae_submitted = EvaluatedSiaeFactory(
            pk=1000, evaluation_campaign=campaign, siae__name="Prim’vert", siae__pk=2000
        )
        evaluated_jobapp_submitted = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_submitted)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=6),
            evaluated_job_application=evaluated_jobapp_submitted,
            # default review_state is PENDING
        )

        with django_capture_on_commit_callbacks(execute=True):
            campaign.transition_to_adversarial_phase()

        # Transitioned to ACCEPTED, the DDETS IAE did not review the documents
        # submitted by SIAE before the transition.
        evaluated_siae_submitted.refresh_from_db()
        assert evaluated_siae_submitted.reviewed_at == datetime.datetime(2023, 1, 2, 11, 11, 11, tzinfo=datetime.UTC)
        assert evaluated_siae_submitted.final_reviewed_at == datetime.datetime(
            2023, 1, 2, 11, 11, 11, tzinfo=datetime.UTC
        )
        assert evaluated_siae_submitted.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

        [siae_email, institution_email] = mail.outbox
        assert institution_email.subject == "[DEV] [Contrôle a posteriori] Passage en phase contradictoire"
        assert institution_email.body == snapshot(name="institution summary email body")
        assert siae_email.subject == f"[DEV] Résultat du contrôle - EI Prim’vert ID-{evaluated_siae_submitted.siae_id}"
        assert siae_email.body == snapshot(name="force accepted email body")

    @freeze_time("2023-01-02 11:11:11")
    def test_transition_to_adversarial_phase_accepted_but_not_reviewed(
        self, django_capture_on_commit_callbacks, snapshot
    ):
        campaign = EvaluationCampaignFactory(institution__name="DDETS 1")
        evaluated_siae_submitted = EvaluatedSiaeFactory(
            evaluation_campaign=campaign, siae__name="Prim’vert", siae__pk=1234
        )
        evaluated_jobapp_submitted = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_submitted)

        assert evaluated_siae_submitted.reviewed_at is None
        # The DDETS IAE set the review_state to ACCEPTED but forgot to validate its review (hence the None reviewed_at)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=6),
            evaluated_job_application=evaluated_jobapp_submitted,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )

        with django_capture_on_commit_callbacks(execute=True):
            campaign.transition_to_adversarial_phase()

        # Transitioned to ACCEPTED, the DDETS IAE review was automatically validated
        evaluated_siae_submitted.refresh_from_db()
        assert evaluated_siae_submitted.reviewed_at == datetime.datetime(2023, 1, 2, 11, 11, 11, tzinfo=datetime.UTC)
        assert evaluated_siae_submitted.final_reviewed_at == datetime.datetime(
            2023, 1, 2, 11, 11, 11, tzinfo=datetime.UTC
        )
        assert evaluated_siae_submitted.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

        [siae_email] = mail.outbox
        assert siae_email.subject == f"[DEV] Résultat du contrôle - EI Prim’vert ID-{evaluated_siae_submitted.siae_id}"
        assert siae_email.body == snapshot(name="positive review email body")

    @freeze_time("2023-01-02 11:11:11")
    def test_transition_to_adversarial_phase_refused_but_not_reviewed(
        self, django_capture_on_commit_callbacks, snapshot
    ):
        campaign = EvaluationCampaignFactory(institution__name="DDETS 1")
        evaluated_siae_submitted = EvaluatedSiaeFactory(
            evaluation_campaign=campaign, siae__name="Prim’vert", siae__pk=1234
        )
        evaluated_jobapp_submitted = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_submitted)

        assert evaluated_siae_submitted.reviewed_at is None
        # The DDETS IAE set the review_state to REFUSED but forgot to validate its review (hence the None reviewed_at)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=6),
            evaluated_job_application=evaluated_jobapp_submitted,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )

        with django_capture_on_commit_callbacks(execute=True):
            campaign.transition_to_adversarial_phase()

        # Transitioned to REFUSED, the DDETS IAE review was automatically validated
        evaluated_siae_submitted.refresh_from_db()
        assert evaluated_siae_submitted.reviewed_at == datetime.datetime(2023, 1, 2, 11, 11, 11, tzinfo=datetime.UTC)
        assert evaluated_siae_submitted.state == evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE

        [siae_email] = mail.outbox
        assert siae_email.subject == f"[DEV] Résultat du contrôle - EI Prim’vert ID-{evaluated_siae_submitted.siae_id}"
        assert siae_email.body == snapshot(name="negative review email body")

    def test_close_no_response(self, django_capture_on_commit_callbacks, snapshot):
        evaluation_campaign = EvaluationCampaignFactory(
            pk=1000,
            institution__name="DDETS 01",
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
        )
        evaluated_siae = EvaluatedSiaeFactory(
            siae__name="Les petits jardins",
            siae__pk=2000,
            evaluation_campaign=evaluation_campaign,
        )
        assert evaluation_campaign.ended_at is None

        with django_capture_on_commit_callbacks(execute=True):
            evaluation_campaign.close()
        assert evaluation_campaign.ended_at is not None
        ended_at = evaluation_campaign.ended_at

        [siae_email, institution_email] = mail.outbox
        assert siae_email.to == list(evaluated_siae.siae.active_admin_members.values_list("email", flat=True))
        assert siae_email.subject == (
            "[DEV] [Contrôle a posteriori] "
            f"Absence de réponse de la structure EI Les petits jardins ID-{evaluated_siae.siae_id}"
        )
        assert siae_email.body == snapshot(name="no docs email body")
        assert sorted(institution_email.to) == sorted(
            evaluation_campaign.institution.active_members.values_list("email", flat=True)
        )
        assert institution_email.subject == "[DEV] [Contrôle a posteriori] Notification des sanctions"
        assert institution_email.body == snapshot(name="sanction notification email body")

        with django_capture_on_commit_callbacks(execute=True):
            evaluation_campaign.close()
        assert ended_at == evaluation_campaign.ended_at
        # No new mail.
        assert len(mail.outbox) == 2

    def test_close_accepted_but_not_reviewed(self, django_capture_on_commit_callbacks, snapshot):
        evaluation_campaign = EvaluationCampaignFactory(
            institution__name="DDETS 01",
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
        )
        evaluated_siae = EvaluatedSiaeFactory(
            siae__name="Les petits jardins",
            siae__pk=2000,
            evaluation_campaign=evaluation_campaign,
            reviewed_at=timezone.now() - datetime.timedelta(days=2),
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=1),
            evaluated_job_application=evaluated_job_application,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        # DDETS accepted the document but forgot to validate
        assert evaluated_siae.final_reviewed_at is None
        assert evaluation_campaign.ended_at is None

        with django_capture_on_commit_callbacks(execute=True):
            evaluation_campaign.close()
        assert evaluation_campaign.ended_at is not None
        # DDETS review was automatically validated
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.final_reviewed_at is not None
        ended_at = evaluation_campaign.ended_at

        [accepted_siae_email] = mail.outbox
        assert accepted_siae_email.to == list(evaluated_siae.siae.active_admin_members.values_list("email", flat=True))
        assert (
            accepted_siae_email.subject
            == f"[DEV] Résultat du contrôle - EI Les petits jardins ID-{evaluated_siae.siae_id}"
        )
        assert accepted_siae_email.body == snapshot(name="accepted email body")

        with django_capture_on_commit_callbacks(execute=True):
            evaluation_campaign.close()
        assert ended_at == evaluation_campaign.ended_at
        # No new mail.
        assert len(mail.outbox) == 1

    def test_close_refused_but_not_reviewed(self, django_capture_on_commit_callbacks, snapshot):
        evaluation_campaign = EvaluationCampaignFactory(
            pk=1000,
            institution__name="DDETS 01",
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
        )
        evaluated_siae = EvaluatedSiaeFactory(
            siae__name="Les petits jardins",
            siae__pk=2000,
            evaluation_campaign=evaluation_campaign,
            reviewed_at=timezone.now() - datetime.timedelta(days=2),
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=1),
            evaluated_job_application=evaluated_job_application,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )
        # DDETS refused the document but forgot to validate
        assert evaluated_siae.final_reviewed_at is None
        assert evaluation_campaign.ended_at is None

        with django_capture_on_commit_callbacks(execute=True):
            evaluation_campaign.close()
        assert evaluation_campaign.ended_at is not None
        # DDETS review was automatically validated
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.final_reviewed_at is not None
        ended_at = evaluation_campaign.ended_at

        [refused_siae_email, institution_email] = mail.outbox
        assert refused_siae_email.to == list(evaluated_siae.siae.active_admin_members.values_list("email", flat=True))
        assert (
            refused_siae_email.subject
            == f"[DEV] Résultat du contrôle - EI Les petits jardins ID-{evaluated_siae.siae_id}"
        )
        assert refused_siae_email.body == snapshot(name="refused email body")

        assert sorted(institution_email.to) == sorted(
            evaluation_campaign.institution.active_members.values_list("email", flat=True)
        )
        assert institution_email.subject == "[DEV] [Contrôle a posteriori] Notification des sanctions"
        assert institution_email.body == snapshot(name="sanction notification email body")

        with django_capture_on_commit_callbacks(execute=True):
            evaluation_campaign.close()
        assert ended_at == evaluation_campaign.ended_at
        # No new mail.
        assert len(mail.outbox) == 2

    def test_freeze(self):
        campaign = EvaluationCampaignFactory()
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign,
        )
        assert evaluated_siae.submission_freezed_at is None

        # Freeze in phase 2
        campaign.freeze(timezone.now())
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.submission_freezed_at is not None

        # Unfreeze via transition_to_adversarial_phase
        campaign.transition_to_adversarial_phase()
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.submission_freezed_at is None

        # Freeze in phase 3
        campaign.freeze(timezone.now())
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.submission_freezed_at is not None

    @freeze_time("2023-01-18 11:11:11")
    def test_institution_submission_freeze_notification(self, django_capture_on_commit_callbacks):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(weeks=3),
            institution__name="DDETS 01",
            name="Campagne de test",
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=campaign)
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae, complete=True)
        with django_capture_on_commit_callbacks(execute=True):
            campaign.freeze(timezone.now())

        assert campaign.submission_freeze_notified_at is not None
        [email] = mail.outbox
        assert (
            email.subject
            == "[DEV] [Contrôle a posteriori] Contrôle des justificatifs à réaliser avant la clôture de phase"
        )

    @freeze_time("2023-01-18 11:11:11")
    def test_institution_submission_freeze_adversarial(self, django_capture_on_commit_callbacks):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            calendar__adversarial_stage_start=timezone.localdate() - relativedelta(weeks=3),
            institution__name="DDETS 01",
            name="Campagne de test",
        )
        evaluated_ = EvaluatedSiaeFactory(
            evaluation_campaign=campaign, reviewed_at=timezone.now() - relativedelta(days=15)
        )
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_, complete=True)
        with django_capture_on_commit_callbacks(execute=True):
            campaign.freeze(timezone.now())

        assert campaign.submission_freeze_notified_at is not None
        [email] = mail.outbox
        assert (
            email.subject
            == "[DEV] [Contrôle a posteriori] Contrôle des justificatifs à réaliser avant la clôture de phase"
        )

    @freeze_time("2023-01-18 11:11:11")
    def test_institution_submission_freeze_notification_ignores_already_notified(
        self, django_capture_on_commit_callbacks
    ):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(weeks=3),
            submission_freeze_notified_at=timezone.now(),
            institution__name="DDETS 01",
            name="Campagne de test",
        )
        evaluated_ = EvaluatedSiaeFactory(evaluation_campaign=campaign)
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_, complete=True)
        with django_capture_on_commit_callbacks(execute=True):
            campaign.freeze(timezone.now())
        assert mail.outbox == []

    @freeze_time("2023-01-18 11:11:11")
    def test_institution_submission_freeze_notification_ignores_siae_evaluated(
        self, django_capture_on_commit_callbacks
    ):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(weeks=3),
            institution__name="DDETS 01",
            name="Campagne de test",
        )
        evaluated_ = EvaluatedSiaeFactory(evaluation_campaign=campaign, reviewed_at=timezone.now())
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_, complete=True)
        with django_capture_on_commit_callbacks(execute=True):
            campaign.freeze(timezone.now())
        assert campaign.submission_freeze_notified_at is None
        assert mail.outbox == []

    @freeze_time("2023-01-18 11:11:11")
    def test_institution_submission_freeze_no_notification_without_docs(self, django_capture_on_commit_callbacks):
        campaign = EvaluationCampaignFactory(evaluations_asked_at=timezone.now() - relativedelta(weeks=3))
        evaluated_ = EvaluatedSiaeFactory(evaluation_campaign=campaign)
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_)
        with django_capture_on_commit_callbacks(execute=True):
            campaign.freeze(timezone.now())
        assert campaign.submission_freeze_notified_at is None
        assert mail.outbox == []

    @freeze_time("2023-01-18 11:11:11")
    def test_institution_submission_freeze_ignores_final_reviewed_at_before_adversarial_start(
        self, django_capture_on_commit_callbacks
    ):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            calendar__adversarial_stage_start=datetime.date(2023, 2, 1),
            institution__name="DDETS 01",
            name="Campagne de test",
        )
        evaluated_ = EvaluatedSiaeFactory(
            evaluation_campaign=campaign,
            reviewed_at=timezone.now() - relativedelta(days=20),
            final_reviewed_at=timezone.now() - relativedelta(days=20),
        )
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_, complete=True)

        with django_capture_on_commit_callbacks(execute=True):
            campaign.freeze(timezone.now())
        assert campaign.submission_freeze_notified_at is None
        assert mail.outbox == []

    @freeze_time("2023-01-18 11:11:11")
    def test_institution_submission_freeze_ignores_final_reviewed_at_after_adversarial_start(
        self, django_capture_on_commit_callbacks
    ):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            calendar__adversarial_stage_start=datetime.date(2023, 1, 1),
            institution__name="DDETS 01",
            name="Campagne de test",
        )
        evaluated_ = EvaluatedSiaeFactory(
            evaluation_campaign=campaign,
            reviewed_at=timezone.now() - relativedelta(days=20),
            final_reviewed_at=timezone.now() - relativedelta(days=20),
        )
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_, complete=True)

        with django_capture_on_commit_callbacks(execute=True):
            campaign.freeze(timezone.now())
        assert campaign.submission_freeze_notified_at is None
        assert mail.outbox == []


class TestEvaluatedSiaeQuerySet:
    def test_for_siae(self):
        company_1 = CompanyFactory()
        company_2 = CompanyFactory()
        EvaluatedSiaeFactory(siae=company_2)

        assert 0 == EvaluatedSiae.objects.for_company(company_1).count()
        assert 1 == EvaluatedSiae.objects.for_company(company_2).count()

    def test_in_progress(self):
        fake_now = timezone.now()
        institution = InstitutionFactory(name="DDETS 01", department="01")

        # evaluations_asked_at is None
        EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=None, evaluation_campaign__institution=institution
        )
        assert 0 == EvaluatedSiae.objects.in_progress().count()

        # ended_at is not None
        EvaluatedSiaeFactory(evaluation_campaign__ended_at=fake_now)
        assert 0 == EvaluatedSiae.objects.in_progress().count()

        # evaluations_asked_at is not None, ended_at is None
        EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=fake_now,
            evaluation_campaign__ended_at=None,
            evaluation_campaign__institution=institution,
        )
        assert 1 == EvaluatedSiae.objects.in_progress().count()


class TestEvaluatedSiaeModel:
    def test_state_unitary(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=fake_now)

        ## unit tests
        # no evaluated_job_application
        assert evaluation_enums.EvaluatedSiaeState.PENDING == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # no evaluated_administrative_criterion
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        assert evaluation_enums.EvaluatedSiaeState.PENDING == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # one evaluated_administrative_criterion
        # empty : proof and submitted_at empty)
        evaluated_administrative_criteria0 = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof=None
        )
        assert evaluation_enums.EvaluatedSiaeState.PENDING == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # with proof
        evaluated_administrative_criteria0.proof = FileFactory()
        evaluated_administrative_criteria0.save(update_fields=["proof"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTABLE == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # PENDING + submitted_at without review
        evaluated_administrative_criteria0.submitted_at = fake_now
        evaluated_administrative_criteria0.save(update_fields=["submitted_at"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # PENDING + submitted_at before review: we still consider that the DDETS IAE can validate the documents
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # PENDING + submitted_at after review
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # with review_state REFUSED, not reviewed : removed, should not exist in real life

        # with review_state REFUSED, reviewed, submitted_at before reviewed_at
        evaluated_administrative_criteria0.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluated_administrative_criteria0.submitted_at <= evaluated_siae.reviewed_at
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # with review_state REFUSED, reviewed, submitted_at after reviewed_at
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluated_administrative_criteria0.submitted_at > evaluated_siae.reviewed_at
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # with review_state REFUSED_2, reviewed, submitted_at after reviewed_at
        evaluated_administrative_criteria0.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # with review_state REFUSED_2, reviewed, submitted_at after reviewed_at, with final_reviewed_at
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.REFUSED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # with review_state REFUSED_2, reviewed, submitted_at after
        # reviewed_at, with final_reviewed_at, with notified_at
        evaluated_siae.notified_at = fake_now
        evaluated_siae.notification_reason = evaluation_enums.EvaluatedSiaeNotificationReason.MISSING_PROOF
        evaluated_siae.notification_text = "Le document n’a pas été transmis."
        evaluated_siae.save(update_fields=["notified_at", "notification_reason", "notification_text"])
        assert evaluation_enums.EvaluatedSiaeState.REFUSED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # with review_state REFUSED_2, reviewed, submitted_at before reviewed_at :
        # removed, should never happen in real life

        # with review_state ACCEPTED not reviewed : removed, should not exist in real life

        # with review_state ACCEPTED reviewed, submitted_at before reviewed_at
        # : removed, should not exist in real life

        # with review_state ACCEPTED reviewed, submitted_at after reviewed_at
        evaluated_administrative_criteria0.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        )
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        review_time = fake_now - relativedelta(days=1)
        evaluated_siae.reviewed_at = review_time
        evaluated_siae.final_reviewed_at = review_time
        evaluated_siae.notified_at = None
        evaluated_siae.notification_reason = None
        evaluated_siae.notification_text = ""
        evaluated_siae.save(
            update_fields=[
                "final_reviewed_at",
                "reviewed_at",
                "notified_at",
                "notification_reason",
                "notification_text",
            ]
        )
        assert evaluated_administrative_criteria0.submitted_at > evaluated_siae.reviewed_at
        assert evaluation_enums.EvaluatedSiaeState.ACCEPTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

    def test_state_integration(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=fake_now)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory.create_batch(
            3,
            evaluated_job_application=evaluated_job_application,
            submitted_at=fake_now,
        )

        # NOT REVIEWED
        # one Pending, one Refused, one Accepted
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            2
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[2].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # one Refused, two Accepted
        evaluated_siae.reviewed_at = fake_now
        evaluated_siae.save(update_fields=["reviewed_at"])
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ACCEPTED == evaluated_siae.state
        del evaluated_siae.state_from_applications
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["final_reviewed_at"])

        # REVIEWED, submitted_at less than reviewed_at
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])

        # one Pending, one Refused, one Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            2
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[2].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # one Refused, two Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # three Accepted
        evaluated_siae.final_reviewed_at = evaluated_siae.reviewed_at + relativedelta(days=1)
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ACCEPTED == evaluated_siae.state
        del evaluated_siae.state_from_applications
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["final_reviewed_at"])

        # REVIEWED, submitted_at greater than reviewed_at
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])

        # one Pending, one Refused, one Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            2
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[2].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # one Refused, two Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state_from_applications

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ACCEPTED == evaluated_siae.state
        del evaluated_siae.state_from_applications

    def test_state_on_closed_campaign_no_criteria(self):
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__ended_at=timezone.now())
        assert evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_no_criteria_notified(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__ended_at=timezone.now() - relativedelta(days=1),
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="Invalide",
        )
        assert evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_not_submitted(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=1),
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_not_submitted_notified(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now() - relativedelta(days=1),
            evaluated_siae__notified_at=timezone.now(),
            evaluated_siae__notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            evaluated_siae__notification_text="Invalide",
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=1),
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_submitted(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
        )
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

    def test_state_on_closed_campaign_criteria_submitted_after_review(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=3),
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
        )
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

    def test_state_on_closed_campaign_criteria_uploaded_after_review(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=3),
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
            evaluated_siae__notified_at=timezone.now(),
            evaluated_siae__notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            evaluated_siae__notification_text="Invalide",
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            # Not submitted.
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_refused_review_validated(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now(),
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_refused_review_validated_notified(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=5),
            evaluated_siae__evaluation_campaign__ended_at=timezone.now() - relativedelta(days=1),
            evaluated_siae__notified_at=timezone.now(),
            evaluated_siae__notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            evaluated_siae__notification_text="Invalide",
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=8),
            submitted_at=timezone.now() - relativedelta(days=7),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_accepted(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=5),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED


@pytest.mark.parametrize(
    "state,frozen,should_display_pending_action_warning",
    [
        (evaluation_enums.EvaluatedSiaeState.PENDING, True, False),
        (evaluation_enums.EvaluatedSiaeState.SUBMITTABLE, True, False),
        (evaluation_enums.EvaluatedSiaeState.SUBMITTED, True, False),
        (evaluation_enums.EvaluatedSiaeState.ACCEPTED, True, False),
        (evaluation_enums.EvaluatedSiaeState.REFUSED, True, False),
        (evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, True, False),
        (evaluation_enums.EvaluatedSiaeState.PENDING, False, True),
        (evaluation_enums.EvaluatedSiaeState.SUBMITTABLE, False, True),
        (evaluation_enums.EvaluatedSiaeState.SUBMITTED, False, False),
        (evaluation_enums.EvaluatedSiaeState.ACCEPTED, False, False),
        (evaluation_enums.EvaluatedSiaeState.REFUSED, False, False),
        (evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, False, True),
    ],
)
def test_should_display_pending_action_warning(state, frozen, should_display_pending_action_warning):
    evaluated_siae = EvaluatedSiaeFactory(submission_freezed_at=timezone.now() if frozen else None)
    # Override state property for faster tests
    with mock.patch.object(EvaluatedSiae, "state", state):
        assert evaluated_siae.should_display_pending_action_warning == should_display_pending_action_warning


class TestEvaluatedJobApplicationModel:
    def test_unicity_constraint(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        criterion = AdministrativeCriteria.objects.first()

        assert EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application, administrative_criteria=criterion
        )
        with pytest.raises(IntegrityError):
            EvaluatedAdministrativeCriteria.objects.create(
                evaluated_job_application=evaluated_job_application, administrative_criteria=criterion
            )

    def test_state(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        assert evaluation_enums.EvaluatedJobApplicationsState.PENDING == evaluated_job_application.compute_state()

        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof=None
        )
        assert evaluation_enums.EvaluatedJobApplicationsState.PROCESSING == evaluated_job_application.compute_state()

        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=["proof"])
        assert evaluation_enums.EvaluatedJobApplicationsState.UPLOADED == evaluated_job_application.compute_state()

        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        assert evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED == evaluated_job_application.compute_state()

        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED == evaluated_job_application.compute_state()

        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedJobApplicationsState.REFUSED == evaluated_job_application.compute_state()

        evaluated_administrative_criteria.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2 == evaluated_job_application.compute_state()

        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED == evaluated_job_application.compute_state()

    def test_state_refused2_has_precedence(self):
        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(weeks=3),
            evaluated_siae__final_reviewed_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            submitted_at=timezone.now(),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            submitted_at=timezone.now() - relativedelta(weeks=4),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )
        assert evaluated_job_application.compute_state() == evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2

    def test_should_select_criteria_with_mock(self, subtests):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        assert (
            evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.PENDING
            == evaluated_job_application.should_select_criteria
        )

        editable_status = [
            evaluation_enums.EvaluatedJobApplicationsState.PROCESSING,
            evaluation_enums.EvaluatedJobApplicationsState.UPLOADED,
        ]

        for state in editable_status:
            with subtests.test(state=state.name):
                with mock.patch.object(EvaluatedJobApplication, "compute_state", return_value=state):
                    assert (
                        evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.EDITABLE
                        == evaluated_job_application.should_select_criteria
                    )

        not_editable_status = [
            state
            for state in evaluation_enums.EvaluatedJobApplicationsState
            if state != evaluation_enums.EvaluatedJobApplicationsState.PENDING and state not in editable_status
        ]

        for state in not_editable_status:
            with subtests.test(state=state.name):
                with mock.patch.object(EvaluatedJobApplication, "compute_state", return_value=state):
                    assert (
                        evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE
                        == evaluated_job_application.should_select_criteria
                    )

        # REVIEWED
        evaluated_siae = evaluated_job_application.evaluated_siae
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        assert (
            evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.PENDING
            == evaluated_job_application.should_select_criteria
        )

        for state in [
            state
            for state in evaluation_enums.EvaluatedJobApplicationsState
            if state != evaluation_enums.EvaluatedJobApplicationsState.PENDING
        ]:
            with subtests.test(state=state.name):
                with mock.patch.object(EvaluatedJobApplication, "compute_state", return_value=state):
                    assert (
                        evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE
                        == evaluated_job_application.should_select_criteria
                    )

    def test_save_selected_criteria(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        criterion1 = AdministrativeCriteria.objects.filter(level=1).first()
        criterion2 = AdministrativeCriteria.objects.filter(level=2).first()

        # nothing to do
        evaluated_job_application.save_selected_criteria(changed_keys=[], cleaned_keys=[])
        assert 0 == EvaluatedAdministrativeCriteria.objects.count()

        # only create criterion1
        evaluated_job_application.save_selected_criteria(changed_keys=[criterion1.key], cleaned_keys=[criterion1.key])
        assert 1 == EvaluatedAdministrativeCriteria.objects.count()
        assert (
            EvaluatedAdministrativeCriteria.objects.first().administrative_criteria
            == AdministrativeCriteria.objects.filter(level=1).first()
        )

        # create criterion2 and delete criterion1
        evaluated_job_application.save_selected_criteria(
            changed_keys=[criterion1.key, criterion2.key], cleaned_keys=[criterion2.key]
        )
        assert 1 == EvaluatedAdministrativeCriteria.objects.count()
        assert (
            EvaluatedAdministrativeCriteria.objects.first().administrative_criteria
            == AdministrativeCriteria.objects.filter(level=2).first()
        )

        # only delete
        evaluated_job_application.save_selected_criteria(changed_keys=[criterion2.key], cleaned_keys=[])
        assert 0 == EvaluatedAdministrativeCriteria.objects.count()

        # delete non-existant criterion does not raise error ^^
        evaluated_job_application.save_selected_criteria(changed_keys=[criterion2.key], cleaned_keys=[])
        assert 0 == EvaluatedAdministrativeCriteria.objects.count()

        # atomic : deletion rolled back when trying to create existing criterion
        evaluated_job_application.save_selected_criteria(
            changed_keys=[criterion1.key, criterion2.key], cleaned_keys=[criterion1.key, criterion2.key]
        )
        with pytest.raises(IntegrityError):
            evaluated_job_application.save_selected_criteria(
                changed_keys=[criterion1.key, criterion2.key], cleaned_keys=[criterion2.key]
            )
        assert 2 == EvaluatedAdministrativeCriteria.objects.count()


class TestEvaluatedAdministrativeCriteriaModel:
    def test_can_upload(self, subtests):
        fake_now = timezone.now()

        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=EvaluatedJobApplicationFactory(),
            proof=None,
        )
        assert evaluated_administrative_criteria.can_upload()

        evaluated_siae = evaluated_administrative_criteria.evaluated_job_application.evaluated_siae
        evaluated_siae.reviewed_at = fake_now
        evaluated_siae.save(update_fields=["reviewed_at"])

        evaluated_administrative_criteria.submitted_at = fake_now
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["submitted_at", "review_state"])
        assert evaluated_administrative_criteria.can_upload()

        for state in [
            state
            for state in evaluation_enums.EvaluatedAdministrativeCriteriaState
            if state != evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        ]:
            with subtests.test(state=state.name):
                evaluated_administrative_criteria.review_state = state
                evaluated_administrative_criteria.save(update_fields=["review_state"])
                assert not evaluated_administrative_criteria.can_upload()


def test_siae_get_active_suspension_functions():
    institution = InstitutionFactory(name="DDETS 01", department="01")
    company = CompanyFactory()
    assert company.get_active_suspension_dates() is None

    # Suspension in the past is inactive and not returned
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=company, evaluation_campaign__institution=institution),
        suspension_dates=InclusiveDateRange(
            timezone.localdate() - relativedelta(years=2), timezone.localdate() - relativedelta(years=1)
        ),
    )
    assert company.get_active_suspension_dates() is None
    assert company.get_active_suspension_text_with_dates() == ""

    # Active suspension
    active_suspension = InclusiveDateRange(
        timezone.localdate() - relativedelta(years=1), timezone.localdate() + relativedelta(years=2)
    )
    active_suspension2 = InclusiveDateRange(
        timezone.localdate() - relativedelta(years=1), timezone.localdate() + relativedelta(years=1)
    )
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=company),
        suspension_dates=active_suspension,
    )
    assert company.get_active_suspension_dates() == active_suspension
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=company, evaluation_campaign__institution=institution),
        suspension_dates=active_suspension2,
    )
    # We still get active_suspension that ends after active_suspension2
    assert company.get_active_suspension_dates() == active_suspension
    explanation = company.get_active_suspension_text_with_dates()
    assert "retrait temporaire" in explanation
    assert (
        f"est effectif depuis le {active_suspension.lower:%d/%m/%Y} "
        f"et le sera jusqu'au {active_suspension.upper:%d/%m/%Y}"
    ) in explanation

    # Suspension without end is prefered
    final_suspension = InclusiveDateRange(timezone.localdate() - relativedelta(years=2))
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=company, evaluation_campaign__institution=institution),
        suspension_dates=final_suspension,
    )
    assert company.get_active_suspension_dates() == final_suspension
    explanation = company.get_active_suspension_text_with_dates()
    assert "retrait définitif" in explanation
    assert f"est effectif depuis le {final_suspension.lower:%d/%m/%Y}." in explanation


def test_final_reviewed_at_after_reviewed_at():
    evaluated_siae = EvaluatedSiaeFactory()

    # final_reviewed_at WITHOUT reviewed_at
    assert evaluated_siae.reviewed_at is None
    evaluated_siae.final_reviewed_at = timezone.now() - datetime.timedelta(days=1)
    # Avoid crashing the database connection because of the IntegrityError
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            evaluated_siae.save()

    # reviewed_at AFTER final_reviewed_at
    evaluated_siae.reviewed_at = timezone.now()
    # Avoid crashing the database connection because of the IntegrityError
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            evaluated_siae.save()
