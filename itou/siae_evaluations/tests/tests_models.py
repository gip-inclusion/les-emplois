import datetime
from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.factories import ApprovalFactory
from itou.eligibility.enums import AdministrativeCriteriaLevel, AuthorKind
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.enums import InstitutionKind
from itou.institutions.factories import InstitutionFactory, InstitutionWith2MembershipFactory
from itou.job_applications.factories import JobApplicationFactory
from itou.job_applications.models import JobApplication, JobApplicationQuerySet, JobApplicationWorkflow
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from itou.siae_evaluations.models import (
    CampaignAlreadyPopulatedException,
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
    Sanctions,
    create_campaigns,
    select_min_max_job_applications,
    validate_institution,
)
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory, SiaeWith2MembershipsFactory
from itou.users.enums import KIND_SIAE_STAFF
from itou.users.factories import JobSeekerFactory
from itou.utils.models import InclusiveDateRange
from itou.utils.perms.user import UserInfo
from itou.utils.test import TestCase


def create_batch_of_job_applications(siae):
    JobApplicationFactory.create_batch(
        evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
        with_approval=True,
        to_siae=siae,
        sender_siae=siae,
        eligibility_diagnosis__author_kind=AuthorKind.SIAE_STAFF,
        eligibility_diagnosis__author_siae=siae,
        hiring_start_at=timezone.now() - relativedelta(months=2),
    )


class EvaluationCampaignMiscMethodsTest(TestCase):
    def test_select_min_max_job_applications(self):
        siae = SiaeFactory()
        job_seeker = JobSeekerFactory()

        # zero job application
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        assert isinstance(qs, JobApplicationQuerySet)
        assert 0 == qs.count()

        # one job applications made by SIAE
        job_application = JobApplicationFactory(to_siae=siae, job_seeker=job_seeker)
        assert job_application == select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).first()
        assert 1 == select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count()

        # under 10 job applications, 20% is below the minimum value of 2 -> select 2
        JobApplicationFactory.create_batch(5, to_siae=siae, job_seeker=job_seeker)
        assert (
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN
            == select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count()
        )

        # from 20 job applications to 100 we have the correct percentage
        JobApplicationFactory.create_batch(55, to_siae=siae, job_seeker=job_seeker)
        assert 12 == select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count()

        # Over 100, stop at the max number -> 20
        JobApplicationFactory.create_batch(50, to_siae=siae, job_seeker=job_seeker)
        assert (
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MAX
            == select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count()
        )


class EvaluationCampaignQuerySetTest(TestCase):
    def test_for_institution(self):
        institution1 = InstitutionFactory()
        EvaluationCampaignFactory(institution=institution1)

        institution2 = InstitutionFactory()
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
    siae = SiaeWith2MembershipsFactory(department="14")
    job_seeker = JobSeekerFactory()
    approval = ApprovalFactory(user=job_seeker)
    diag = EligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        author_kind=AuthorKind.SIAE_STAFF,
        author_siae=siae,
        author=siae.members.first(),
    )
    job_app = JobApplicationFactory(
        job_seeker=job_seeker,
        approval=approval,
        to_siae=siae,
        sender_siae=siae,
        eligibility_diagnosis=diag,
        hiring_start_at=timezone.now() - relativedelta(months=2),
        state=JobApplicationWorkflow.STATE_ACCEPTED,
    )
    return {
        "approval": approval,
        "diag": diag,
        "job_app": job_app,
        "siae": siae,
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

    @pytest.mark.parametrize("kind", [k for k in SiaeKind if k not in evaluation_enums.EvaluationSiaesKind.Evaluable])
    def test_siae_not_eligible_kind(self, kind, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        siae = campaign_eligible_job_app_objects["siae"]
        siae.kind = kind
        siae.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_job_application_not_accepted(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        job_app = campaign_eligible_job_app_objects["job_app"]
        job_app.state = JobApplicationWorkflow.STATE_REFUSED
        job_app.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_job_application_not_in_period(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        job_app = campaign_eligible_job_app_objects["job_app"]
        job_app.hiring_start_at = timezone.now() - relativedelta(months=10)
        job_app.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_eligibility_diag_not_made_by_siae_staff(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        diag = campaign_eligible_job_app_objects["diag"]
        diag.author_kind = AuthorKind.PRESCRIBER
        diag.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_eligibility_diag_made_by_another_siae(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        diag = campaign_eligible_job_app_objects["diag"]
        diag.author_siae = SiaeFactory()
        diag.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())

    def test_approval_does_not_start_with_itou_prefix(self, campaign_eligible_job_app_objects):
        evaluation_campaign = EvaluationCampaignFactory()
        approval = campaign_eligible_job_app_objects["approval"]
        approval.number = "0123456789"
        approval.save()
        assert [] == list(evaluation_campaign.eligible_job_applications())


class EvaluationCampaignManagerTest(TestCase):
    def test_validate_institution(self):

        with pytest.raises(ValidationError):
            validate_institution(0)

        for kind in [k for k in InstitutionKind if k != InstitutionKind.DDETS]:
            with self.subTest(kind=kind):
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

    def test_create_campaigns(self):
        evaluated_period_start_at = timezone.now() - relativedelta(months=2)
        evaluated_period_end_at = timezone.now() - relativedelta(months=1)
        ratio_selection_end_at = timezone.now() + relativedelta(months=1)

        # not DDETS
        for kind in [k for k in InstitutionKind if k != InstitutionKind.DDETS]:
            with self.subTest(kind=kind):
                InstitutionFactory(kind=kind)
                assert 0 == create_campaigns(
                    evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at
                )
                assert 0 == EvaluationCampaign.objects.all().count()
                assert len(mail.outbox) == 0

        # institution DDETS
        InstitutionWith2MembershipFactory.create_batch(2, kind=InstitutionKind.DDETS)
        assert 2 == create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at)
        assert 2 == EvaluationCampaign.objects.all().count()

        # An email should have been sent to the institution members.
        assert len(mail.outbox) == 2
        email = mail.outbox[0]
        assert len(email.to) == 2
        email = mail.outbox[1]
        assert len(email.to) == 2

    def test_eligible_siaes(self):

        evaluation_campaign = EvaluationCampaignFactory()

        # siae1 got 1 job application
        siae1 = SiaeFactory(department="14")
        JobApplicationFactory(
            with_approval=True,
            to_siae=siae1,
            sender_siae=siae1,
            eligibility_diagnosis__author_kind=AuthorKind.SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae1,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        # siae2 got 2 job applications
        siae2 = SiaeFactory(department="14")
        create_batch_of_job_applications(siae2)

        eligible_siaes_res = evaluation_campaign.eligible_siaes()
        assert 1 == eligible_siaes_res.count()
        assert {
            "to_siae": siae2.id,
            "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
        } in eligible_siaes_res

        # adding 2 more job applications to siae2
        create_batch_of_job_applications(siae2)

        eligible_siaes_res = evaluation_campaign.eligible_siaes()
        assert 1 == eligible_siaes_res.count()
        assert {
            "to_siae": siae2.id,
            "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN * 2,
        } in eligible_siaes_res

    def test_number_of_siaes_to_select(self):
        evaluation_campaign = EvaluationCampaignFactory()
        assert 0 == evaluation_campaign.number_of_siaes_to_select()

        for _ in range(3):
            siae = SiaeFactory(department="14")
            create_batch_of_job_applications(siae)

        assert 1 == evaluation_campaign.number_of_siaes_to_select()

        for _ in range(3):
            siae = SiaeFactory(department="14")
            create_batch_of_job_applications(siae)

        assert 2 == evaluation_campaign.number_of_siaes_to_select()

    def test_eligible_siaes_under_ratio(self):
        evaluation_campaign = EvaluationCampaignFactory()

        for _ in range(6):
            siae = SiaeFactory(department="14")
            create_batch_of_job_applications(siae)

        assert 2 == evaluation_campaign.eligible_siaes_under_ratio().count()

    def test_populate(self):
        # integration tests
        evaluation_campaign = EvaluationCampaignFactory()
        siae = SiaeFactory(department=evaluation_campaign.institution.department, with_membership=True)
        job_seeker = JobSeekerFactory()
        user = siae.members.first()
        user_info = UserInfo(
            user=user, kind=KIND_SIAE_STAFF, siae=siae, prescriber_organization=None, is_authorized_prescriber=False
        )
        criteria1 = AdministrativeCriteria.objects.get(
            level=AdministrativeCriteriaLevel.LEVEL_1, name="Bénéficiaire du RSA"
        )
        eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=[criteria1]
        )
        JobApplicationFactory.create_batch(
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
            with_approval=True,
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis=eligibility_diagnosis,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        fake_now = timezone.now() - relativedelta(weeks=1)

        assert 0 == EvaluatedSiae.objects.all().count()
        assert 0 == EvaluatedJobApplication.objects.all().count()

        with self.assertNumQueries(
            1  # SAVEPOINT from transaction.atomic()
            + 1  # UPDATE SET percent_set_at
            + 1  # COUNT eligible job applications
            + 1  # SELECT to_siae_id and job application count for SIAE with at least 2 auto-prescriptions.
            + 1  # SELECT SIAE details
            + 1  # INSERT EvaluatedSiae
            + 1  # COUNT eligible job applications
            + 1  # SELECT job applications to evaluate
            + 1  # INSERT EvaluatedJobApplication
            + 1  # SELECT SIAE convention
            + 1  # SELECT SIAE admin users
            + 1  # SELECT institution users
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
            with self.subTest(evaluated_job_application_pk=evaluated_job_application.pk):
                assert evaluated_siae == evaluated_job_application.evaluated_siae

        # retry on populated campaign
        with pytest.raises(CampaignAlreadyPopulatedException):
            evaluation_campaign.populate(fake_now)

    @freeze_time("2023-01-02 11:11:11")
    def test_transition_to_adversarial_phase(self):
        ignored_siae = EvaluatedSiaeFactory()  # will be ignored
        campaign = EvaluationCampaignFactory(institution__name="DDETS 1")
        # Did not select eligibility criteria to justify.
        evaluated_siae_no_response = EvaluatedSiaeFactory(
            evaluation_campaign=campaign, siae__name="Les grands jardins"
        )
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_no_response)
        evaluated_siae_no_docs = EvaluatedSiaeFactory(evaluation_campaign=campaign, siae__name="Les petits jardins")
        evaluated_jobapp_no_docs = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_no_docs)
        EvaluatedAdministrativeCriteriaFactory(
            uploaded_at=timezone.now() - relativedelta(days=7),
            evaluated_job_application=evaluated_jobapp_no_docs,
            # default review_state is PENDING
        )
        evaluated_siae_submitted = EvaluatedSiaeFactory(evaluation_campaign=campaign, siae__name="Prim’vert")
        evaluated_jobapp_submitted = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_submitted)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=6),
            evaluated_job_application=evaluated_jobapp_submitted,
            # default review_state is PENDING
        )
        accepted_ts = timezone.now() - relativedelta(days=1)
        evaluated_siae_accepted = EvaluatedSiaeFactory(
            evaluation_campaign=campaign,
            siae__name="Geo",
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
            evaluation_campaign=campaign,
            siae__name="Geo",
            reviewed_at=refused_ts,
        )
        evaluated_jobapp_refused = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_refused)
        EvaluatedAdministrativeCriteriaFactory(
            submitted_at=timezone.now() - relativedelta(days=4),
            evaluated_job_application=evaluated_jobapp_refused,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )

        campaign.transition_to_adversarial_phase()

        assert ignored_siae == EvaluatedSiae.objects.get(reviewed_at__isnull=True)

        # Transitioned to ACCEPTED, the DDETS did not review the documents
        # submitted by SIAE before the transition.
        evaluated_siae_submitted.refresh_from_db()
        assert evaluated_siae_submitted.reviewed_at == datetime.datetime(
            2023, 1, 2, 11, 11, 11, tzinfo=datetime.timezone.utc
        )
        assert evaluated_siae_submitted.final_reviewed_at == datetime.datetime(
            2023, 1, 2, 11, 11, 11, tzinfo=datetime.timezone.utc
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

        [siae_no_response_email, siae_no_docs_email, institution_email] = sorted(
            mail.outbox, key=lambda mail: mail.subject
        )
        assert (
            siae_no_response_email.subject
            == f"Résultat du contrôle - EI Les grands jardins ID-{evaluated_siae_no_response.siae_id}"
        )
        assert siae_no_response_email.body == (
            "Bonjour,\n\n"
            "Sauf erreur de notre part, vous n’avez pas transmis les justificatifs dans le cadre du contrôle a "
            "posteriori sur vos embauches réalisées en auto-prescription.\n\n"
            "La DDETS 1 ne peut donc pas faire de contrôle, par conséquent vous entrez dans une phase dite "
            "contradictoire de 6 semaines (durant laquelle il vous faut transmettre les justificatifs demandés) et "
            "qui se clôturera sur une décision (validation ou sanction pouvant aller jusqu’à un retrait d’aide au "
            "poste) conformément à l’instruction N° DGEFP/SDPAE/MIP/2022/83 du 5 avril 2022 relative à la mise en "
            "œuvre opérationnelle du contrôle a posteriori des recrutements en auto-prescription prévu par les "
            "articles R. 5132-1-12 à R. 5132-1-17 du code du travail.\n\n"
            "Pour transmettre les justificatifs, rendez-vous sur le tableau de bord de "
            f"EI Les grands jardins ID-{evaluated_siae_no_response.siae_id} à la rubrique "
            "“Justifier mes auto-prescriptions”.\n"
            f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae_no_response.pk}/\n\n"
            "En cas de besoin, vous pouvez consulter ce mode d’emploi.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://127.0.0.1:8000"
        )

        assert (
            siae_no_docs_email.subject
            == f"Résultat du contrôle - EI Les petits jardins ID-{evaluated_siae_no_docs.siae_id}"
        )
        assert siae_no_docs_email.body == (
            "Bonjour,\n\n"
            "Sauf erreur de notre part, vous n’avez pas transmis les justificatifs dans le cadre du contrôle a "
            "posteriori sur vos embauches réalisées en auto-prescription.\n\n"
            "La DDETS 1 ne peut donc pas faire de contrôle, par conséquent vous entrez dans une phase dite "
            "contradictoire de 6 semaines (durant laquelle il vous faut transmettre les justificatifs demandés) et "
            "qui se clôturera sur une décision (validation ou sanction pouvant aller jusqu’à un retrait d’aide au "
            "poste) conformément à l’instruction N° DGEFP/SDPAE/MIP/2022/83 du 5 avril 2022 relative à la mise en "
            "œuvre opérationnelle du contrôle a posteriori des recrutements en auto-prescription prévu par les "
            "articles R. 5132-1-12 à R. 5132-1-17 du code du travail.\n\n"
            "Pour transmettre les justificatifs, rendez-vous sur le tableau de bord de "
            f"EI Les petits jardins ID-{evaluated_siae_no_docs.siae_id} à la rubrique "
            "“Justifier mes auto-prescriptions”.\n"
            f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae_no_docs.pk}/\n\n"
            "En cas de besoin, vous pouvez consulter ce mode d’emploi.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://127.0.0.1:8000"
        )

        assert institution_email.subject == (
            "[Contrôle a posteriori] "
            "Liste des SIAE n’ayant pas transmis les justificatifs de leurs auto-prescriptions"
        )
        assert institution_email.body == (
            "Bonjour,\n\n"
            "Vous trouverez ci-dessous la liste des SIAE qui n’ont transmis aucun justificatif dans le cadre du "
            "contrôle a posteriori :\n\n"
            f"- EI Les grands jardins ID-{evaluated_siae_no_response.siae_id}\n\n"
            f"- EI Les petits jardins ID-{evaluated_siae_no_docs.siae_id}\n\n"
            "Ces structures n’ayant pas transmis les justificatifs dans le délai des 6 semaines passent "
            "automatiquement en phase contradictoire et disposent à nouveau de 6 semaines pour se manifester.\n\n"
            "N’hésitez pas à les contacter afin de comprendre les éventuelles difficultés rencontrées pour "
            "transmettre les justificatifs.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://127.0.0.1:8000"
        )

    def test_close(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution__name="DDETS 01",
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
        )
        evaluated_siae = EvaluatedSiaeFactory(
            siae__name="Les petits jardins",
            evaluation_campaign=evaluation_campaign,
        )
        assert evaluation_campaign.ended_at is None

        evaluation_campaign.close()
        assert evaluation_campaign.ended_at is not None
        ended_at = evaluation_campaign.ended_at

        [siae_email, institution_email] = mail.outbox
        assert siae_email.to == list(evaluated_siae.siae.active_admin_members.values_list("email", flat=True))
        assert siae_email.subject == (
            "[Contrôle a posteriori] "
            f"Absence de réponse de la structure EI Les petits jardins ID-{evaluated_siae.siae_id}"
        )
        assert siae_email.body == (
            "Bonjour,\n\n"
            "Sauf erreur de notre part, vous n’avez pas transmis les justificatifs demandés dans le cadre du contrôle "
            "a posteriori sur vos embauches réalisées en auto-prescription entre le 01 Janvier 2022 et le 30 "
            "Septembre 2022.\n\n"
            "La DDETS 01 ne peut donc pas faire de contrôle, par conséquent votre résultat concernant cette procédure "
            "est négatif (vous serez alerté des sanctions éventuelles concernant votre SIAE prochainement) "
            "conformément à l’instruction N° DGEFP/SDPAE/MIP/2022/83 du 5 avril 2022 relative à la mise en œuvre "
            "opérationnelle du contrôle a posteriori des recrutements en auto-prescription prévu par les articles "
            "R. 5132-1-12 à R. 5132-1-17 du code du travail.\n\n"
            "Pour plus d’informations, vous pouvez vous rapprocher de la DDETS 01.\n\n"
            "Si vous avez déjà pris contact avec votre DDETS, merci de ne pas tenir compte de ce courriel.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://127.0.0.1:8000"
        )
        assert sorted(institution_email.to) == sorted(
            evaluation_campaign.institution.active_members.values_list("email", flat=True)
        )
        assert institution_email.subject == "[Contrôle a posteriori] Notification des sanctions"
        assert institution_email.body == (
            "Bonjour,\n\n"
            "Suite au dernier contrôle a posteriori, une ou plusieurs SIAE de votre département ont obtenu un "
            "résultat négatif.\n"
            "Conformément au  Décret n° 2021-1128 du 30 août 2021 relatif à l'insertion par l'activité économique, "
            "les manquements constatés ainsi que les sanctions envisagées doivent être notifiés aux SIAE.\n\n"
            "Veuillez vous connecter sur votre espace des emplois de l’inclusion afin d’effectuer cette démarche.\n"
            f"http://127.0.0.1:8000/siae_evaluation/institution_evaluated_siae_list/{evaluation_campaign.pk}/\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://127.0.0.1:8000"
        )

        evaluation_campaign.close()
        assert ended_at == evaluation_campaign.ended_at
        # No new mail.
        assert len(mail.outbox) == 2


class EvaluatedSiaeQuerySetTest(TestCase):
    def test_for_siae(self):
        siae1 = SiaeFactory()
        siae2 = SiaeFactory()
        EvaluatedSiaeFactory(siae=siae2)

        assert 0 == EvaluatedSiae.objects.for_siae(siae1).count()
        assert 1 == EvaluatedSiae.objects.for_siae(siae2).count()

    def test_in_progress(self):
        fake_now = timezone.now()

        # evaluations_asked_at is None
        EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=None)
        assert 0 == EvaluatedSiae.objects.in_progress().count()

        # ended_at is not None
        EvaluatedSiaeFactory(evaluation_campaign__ended_at=fake_now)
        assert 0 == EvaluatedSiae.objects.in_progress().count()

        # evaluations_asked_at is not None, ended_at is None
        EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=fake_now, evaluation_campaign__ended_at=None)
        assert 1 == EvaluatedSiae.objects.in_progress().count()


class EvaluatedSiaeModelTest(TestCase):
    def test_state_unitary(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=fake_now)

        ## unit tests
        # no evaluated_job_application
        assert evaluation_enums.EvaluatedSiaeState.PENDING == evaluated_siae.state
        del evaluated_siae.state

        # no evaluated_administrative_criterion
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        assert evaluation_enums.EvaluatedSiaeState.PENDING == evaluated_siae.state
        del evaluated_siae.state

        # one evaluated_administrative_criterion
        # empty : proof_url and submitted_at empty)
        evaluated_administrative_criteria0 = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof_url=""
        )
        assert evaluation_enums.EvaluatedSiaeState.PENDING == evaluated_siae.state
        del evaluated_siae.state

        # with proof_url
        evaluated_administrative_criteria0.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria0.save(update_fields=["proof_url"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTABLE == evaluated_siae.state
        del evaluated_siae.state

        # PENDING + submitted_at without review
        evaluated_administrative_criteria0.submitted_at = fake_now
        evaluated_administrative_criteria0.save(update_fields=["submitted_at"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state

        # PENDING + submitted_at before review: we still consider that the DDETS can validate the documents
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state

        # PENDING + submitted_at after review
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.SUBMITTED == evaluated_siae.state
        del evaluated_siae.state

        # with review_state REFUSED, not reviewed : removed, should not exist in real life

        # with review_state REFUSED, reviewed, submitted_at before reviewed_at
        evaluated_administrative_criteria0.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluated_administrative_criteria0.submitted_at <= evaluated_siae.reviewed_at
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state

        # with review_state REFUSED, reviewed, submitted_at after reviewed_at
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluated_administrative_criteria0.submitted_at > evaluated_siae.reviewed_at
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state

        # with review_state REFUSED_2, reviewed, submitted_at after reviewed_at
        evaluated_administrative_criteria0.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state

        # with review_state REFUSED_2, reviewed, submitted_at after reviewed_at, with final_reviewed_at
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        assert evaluation_enums.EvaluatedSiaeState.NOTIFICATION_PENDING == evaluated_siae.state
        del evaluated_siae.state

        # with review_state REFUSED_2, reviewed, submitted_at after
        # reviewed_at, with final_reviewed_at, with notified_at
        evaluated_siae.notified_at = fake_now
        evaluated_siae.notification_reason = evaluation_enums.EvaluatedSiaeNotificationReason.MISSING_PROOF
        evaluated_siae.notification_text = "Le document n’a pas été transmis."
        evaluated_siae.save(update_fields=["notified_at", "notification_reason", "notification_text"])
        assert evaluation_enums.EvaluatedSiaeState.REFUSED == evaluated_siae.state
        del evaluated_siae.state

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
        del evaluated_siae.state

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
        del evaluated_siae.state

        # one Refused, two Accepted
        evaluated_siae.reviewed_at = fake_now
        evaluated_siae.save(update_fields=["reviewed_at"])
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ACCEPTED == evaluated_siae.state
        del evaluated_siae.state
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
        del evaluated_siae.state

        # one Refused, two Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ACCEPTED == evaluated_siae.state
        del evaluated_siae.state
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
        del evaluated_siae.state

        # one Refused, two Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE == evaluated_siae.state
        del evaluated_siae.state

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        assert evaluation_enums.EvaluatedSiaeState.ACCEPTED == evaluated_siae.state
        del evaluated_siae.state

    def test_state_on_closed_campaign_no_criteria(self):
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__ended_at=timezone.now())
        assert evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.NOTIFICATION_PENDING

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
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.NOTIFICATION_PENDING

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

    def test_state_on_closed_campaign_criteria_refused_review_not_validated(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=5),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

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
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.NOTIFICATION_PENDING

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


class EvaluatedJobApplicationModelTest(TestCase):
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
            evaluated_job_application=evaluated_job_application, proof_url=""
        )
        assert evaluation_enums.EvaluatedJobApplicationsState.PROCESSING == evaluated_job_application.compute_state()

        evaluated_administrative_criteria.proof_url = "https://www.test.com"
        evaluated_administrative_criteria.save(update_fields=["proof_url"])
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

    def test_should_select_criteria_with_mock(self):
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
            with self.subTest(state=state):
                with mock.patch.object(EvaluatedJobApplication, "compute_state", return_value=state):
                    assert (
                        evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.EDITABLE
                        == evaluated_job_application.should_select_criteria
                    )

        not_editable_status = [
            state
            for state in evaluation_enums.EvaluatedJobApplicationsState.choices
            if state != evaluation_enums.EvaluatedJobApplicationsState.PENDING and state not in editable_status
        ]

        for state in not_editable_status:
            with self.subTest(state=state):
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
            for state in evaluation_enums.EvaluatedJobApplicationsState.choices
            if state != evaluation_enums.EvaluatedJobApplicationsState.PENDING
        ]:
            with self.subTest(state=state):
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


class EvaluatedAdministrativeCriteriaModelTest(TestCase):
    def test_can_upload(self):
        fake_now = timezone.now()

        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=EvaluatedJobApplicationFactory(),
            proof_url="",
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
            for state, _ in evaluation_enums.EvaluatedAdministrativeCriteriaState.choices
            if state != evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        ]:
            with self.subTest(state=state):
                evaluated_administrative_criteria.review_state = state
                evaluated_administrative_criteria.save(update_fields=["review_state"])
                assert not evaluated_administrative_criteria.can_upload()


def test_siae_get_active_suspension_functions():
    siae = SiaeFactory()
    assert siae.get_active_suspension_dates() is None

    # Suspension in the past is inactive and not returned
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=siae),
        suspension_dates=InclusiveDateRange(
            timezone.localdate() - relativedelta(years=2), timezone.localdate() - relativedelta(years=1)
        ),
    )
    assert siae.get_active_suspension_dates() is None
    assert siae.get_active_suspension_text_with_dates() == ""

    # Active suspension
    active_suspension = InclusiveDateRange(
        timezone.localdate() - relativedelta(years=1), timezone.localdate() + relativedelta(years=2)
    )
    active_suspension2 = InclusiveDateRange(
        timezone.localdate() - relativedelta(years=1), timezone.localdate() + relativedelta(years=1)
    )
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=siae),
        suspension_dates=active_suspension,
    )
    assert siae.get_active_suspension_dates() == active_suspension
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=siae),
        suspension_dates=active_suspension2,
    )
    # We still get active_suspension that ends after active_suspension2
    assert siae.get_active_suspension_dates() == active_suspension
    explanation = siae.get_active_suspension_text_with_dates()
    assert "retrait temporaire" in explanation
    assert (
        f"est effectif depuis le {active_suspension.lower:%d/%m/%Y} "
        f"et le sera jusqu'au {active_suspension.upper:%d/%m/%Y}"
    ) in explanation

    # Suspension without end is prefered
    final_suspension = InclusiveDateRange(timezone.localdate() - relativedelta(years=2))
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=siae),
        suspension_dates=final_suspension,
    )
    assert siae.get_active_suspension_dates() == final_suspension
    explanation = siae.get_active_suspension_text_with_dates()
    assert "retrait définitif" in explanation
    assert f"est effectif depuis le {final_suspension.lower:%d/%m/%Y}." in explanation
