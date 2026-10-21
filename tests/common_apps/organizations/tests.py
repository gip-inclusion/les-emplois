import datetime
import random
from functools import partial

import pytest
from django.apps import apps
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.api.models import CompanyToken
from itou.cities.models import City
from itou.common_apps.organizations import transfer
from itou.communications.models import NotificationSettings
from itou.companies import enums as companies_enums, models as companies_models
from itou.eligibility import enums as eligibility_enums
from itou.employee_record.models import EmployeeRecord
from itou.geiq_assessments.models import Assessment
from itou.insertion import models as insertion_models
from itou.institutions.models import Institution
from itou.job_applications import models as job_applications_models
from itou.job_applications.enums import SenderKind
from itou.jobs.models import Appellation
from itou.prescribers import models as prescribers_models
from itou.rdv_insertion import models as rdv_insertion_models
from itou.users import enums as users_enums, models as users_models
from tests.approvals import factories as approvals_factories
from tests.companies import factories as companies_factories
from tests.eligibility import factories as eligibility_factories
from tests.geiq_assessments.factories import AssessmentFactory
from tests.insertion.factories import OrientationFactory
from tests.institutions.factories import InstitutionFactory
from tests.invitations import factories as invitations_factories
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers import factories as prescribers_factories
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users import factories as users_factories


def assert_set_admin_role_creation(user, organization, mailoutbox):
    # New admin.
    assert user in organization.active_admin_members

    # The admin should receive a valid email
    [email] = mailoutbox
    assert "[TEST] Votre rôle d’administrateur" == email.subject
    assert (
        "Vous avez désormais le statut d’administrateur sur l’espace professionnel de "
        f"votre organisation {organization.name} ({organization.kind})"
    ) in email.body
    assert email.to[0] == user.email

    if isinstance(organization, prescribers_models.PrescriberOrganization):
        assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/14737265161617" in email.body
    elif isinstance(organization, Institution):
        assert "https://aide.emplois.inclusion.beta.gouv.fr/" not in email.body
    elif isinstance(organization, companies_models.Company):
        if organization.kind in [
            companies_enums.CompanyKind.ACI,
            companies_enums.CompanyKind.AI,
            companies_enums.CompanyKind.EI,
            companies_enums.CompanyKind.ETTI,
            companies_enums.CompanyKind.EITI,
        ]:
            assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/14738355467409" in email.body
        elif organization.kind in [
            companies_enums.CompanyKind.EA,
            companies_enums.CompanyKind.EATT,
            companies_enums.CompanyKind.OPCS,
        ]:
            assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/16925381169681" in email.body
        elif organization.kind == companies_enums.CompanyKind.GEIQ:
            assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/categories/15209741332113" in email.body
        else:
            raise AssertionError("Invalid siae kind")
    else:
        raise AssertionError("Invalid user kind")


def assert_set_admin_role_removal(user, organization, mailoutbox):
    # Admin removal.
    assert user not in organization.active_admin_members

    # The admin should receive a valid email
    [email] = mailoutbox
    assert f"[TEST] [Désactivation] Vous n'êtes plus administrateur de {organization.display_name}" == email.subject
    assert "Un administrateur vous a retiré les droits d'administrateur d'une structure" in email.body
    assert email.to[0] == user.email


@pytest.mark.parametrize(
    "factory,expected",
    (
        (prescribers_factories.PrescriberOrganizationFactory, "orienteur"),
        (partial(prescribers_factories.PrescriberOrganizationFactory, authorized=True), "prescripteur habilité"),
        (companies_factories.CompanyFactory, "employeur"),
        (InstitutionFactory, "institutionnel"),
    ),
)
def test_member_kind_display(factory, expected):
    org = factory()
    assert org.member_kind_display == expected


class TestOrganizationTransfer:
    def _model_sanity_check(self, model):
        IGNORED_MODELS = {
            companies_models.Company: {
                (CompanyToken, "companies"),
                (companies_models.Contract, "company"),
                (companies_models.ProSupportReport, "company"),
                (companies_models.SiaeConvention, "siaes"),
                (Assessment, "companies"),  # handled through `Assessment.companies.through`
                (insertion_models.MobilizationEmail, "sender_company"),
                (insertion_models.MobilizationEvent, "company"),
                (Appellation, "company"),  # handled through `JobDescription`
                (job_applications_models.JobApplicationComment, "company"),
                (job_applications_models.JobApplicationTransitionLog, "target_company"),
                (rdv_insertion_models.Appointment, "company"),
                (rdv_insertion_models.InvitationRequest, "company"),
                (users_models.User, "created_company_set"),
                (users_models.User, "company"),  # handled through `CompanyMembership`
                (City, "company"),
                (NotificationSettings, "company"),
            },
            prescribers_models.PrescriberOrganization: {
                (insertion_models.MobilizationEmail, "sender_prescriber_organization"),
                (insertion_models.MobilizationEvent, "prescriber_organization"),
                (users_models.User, "authorization_status_set"),
                (users_models.User, "created_prescriber_organization_set"),
                (users_models.User, "prescriberorganization"),  # handled through `PrescriberMembership`
                (City, "prescriberorganization"),
                (NotificationSettings, "prescriber_organization"),
            },
        }

        relation_fields = {
            (m, f.name)
            for m in apps.get_models()
            for f in m._meta.get_fields()
            if f.is_relation and f.related_model is model
        }
        SPECS = transfer.MODEL_TRANSFER_SPECS[model]
        transferred_fields = {
            (spec["related_model"], spec["related_model_field"])
            for spec in SPECS.values()
            if spec.get("related_model")
        }
        if model is companies_models.Company:
            # Remove fields transferred via TRANSFER_FIELDS but missing when going through models
            transferred_fields -= {
                (
                    EmployeeRecord,
                    "job_application__to_company",
                ),  # already transferred through job applications
                (
                    Assessment.companies.through,
                    "company",
                ),  # "through" tables don't get picked up
            }
        assert not transferred_fields & IGNORED_MODELS[model], transferred_fields & IGNORED_MODELS[model]
        assert relation_fields == transferred_fields | IGNORED_MODELS[model], relation_fields ^ (
            transferred_fields | IGNORED_MODELS[model]
        )

    def test_consistency_checks(self):
        assert (transfer.COMPANY_TRANSFER_FIELDS | transfer.PRESCRIBERORG_TRANSFER_FIELDS) == set(
            transfer.TransferField
        )
        assert set(transfer.COMPANY_TRANSFER_SPECS) == transfer.COMPANY_TRANSFER_FIELDS
        assert set(transfer.PRESCRIBERORG_TRANSFER_SPECS) == transfer.PRESCRIBERORG_TRANSFER_FIELDS
        self._model_sanity_check(companies_models.Company)
        self._model_sanity_check(prescribers_models.PrescriberOrganization)

    def test_transfer_between_institutions(self):
        from_institution = InstitutionFactory()
        to_institution = InstitutionFactory()

        with pytest.raises(AssertionError, match="Cannot transfer data between institutions"):
            transfer.transfer_org_data(
                from_institution,
                to_institution,
                random.choice((transfer.COMPANY_TRANSFER_FIELDS, transfer.PRESCRIBERORG_TRANSFER_FIELDS)),
                False,
            )

    def test_transfer_between_company_and_prescriberorg(self):
        from_org = companies_factories.CompanyFactory()
        to_org = prescribers_factories.PrescriberOrganizationFactory()

        with pytest.raises(AssertionError, match="Cannot transfer data between organizations of different kind"):
            transfer.transfer_org_data(
                from_org,
                to_org,
                random.choice((transfer.COMPANY_TRANSFER_FIELDS, transfer.PRESCRIBERORG_TRANSFER_FIELDS)),
                False,
            )

    def test_transfer_to_oneself(self):
        from_org = companies_factories.CompanyFactory()

        with pytest.raises(AssertionError, match="Cannot transfer from one organization to itself"):
            transfer.transfer_org_data(from_org, from_org, transfer.COMPANY_TRANSFER_FIELDS, False)

    def test_transfer_from_asp_company_to_antenna(self):
        from_company = companies_factories.CompanyFactory(source=companies_enums.CompanySource.ASP)
        to_company = companies_factories.CompanyFactory(source=companies_enums.CompanySource.USER_CREATED)

        with pytest.raises(
            transfer.TransferError,
            match="Impossible de transférer d'une entreprise provenant de l'ASP vers une antenne",
        ):
            transfer.transfer_org_data(from_company, to_company, transfer.COMPANY_TRANSFER_FIELDS, False)

    def test_transfer_from_authorized_to_unauthorized(self):
        from_org = prescribers_factories.PrescriberOrganizationFactory(authorized=True)
        to_org = prescribers_factories.PrescriberOrganizationFactory()

        with pytest.raises(
            transfer.TransferError,
            match="Impossible de transférer d'une organisation habilitée vers une organisation non habilitée",
        ):
            transfer.transfer_org_data(from_org, to_org, transfer.PRESCRIBERORG_TRANSFER_FIELDS, False)

    def test_transfer_iae_objects_to_geiq(self):
        siae = companies_factories.CompanyFactory(subject_to_iae_rules=True)
        EvaluatedSiaeFactory(siae=siae)
        geiq = companies_factories.CompanyFactory(kind=companies_enums.CompanyKind.GEIQ)

        with pytest.raises(
            transfer.TransferError, match="Objets impossibles à transférer hors-IAE: Contrôles a posteriori IAE"
        ):
            transfer.transfer_org_data(siae, geiq, transfer.COMPANY_TRANSFER_FIELDS, False)

    def test_transfer_geiq_objects_to_iae(self):
        geiq_diag = eligibility_factories.GEIQEligibilityDiagnosisFactory(from_employer=True)
        geiq = geiq_diag.author_geiq
        siae = companies_factories.CompanyFactory(subject_to_iae_rules=True)

        with pytest.raises(
            transfer.TransferError, match="Objets impossibles à transférer hors-GEIQ: Diagnostics GEIQ créés"
        ):
            transfer.transfer_org_data(geiq, siae, transfer.COMPANY_TRANSFER_FIELDS, False)

    @pytest.mark.parametrize("is_geiq", [False, True])
    @pytest.mark.parametrize("disable_from_org", [False, True])
    def test_company_transfer(self, is_geiq, disable_from_org):
        company_kind_kwargs = {"kind": companies_enums.CompanyKind.GEIQ} if is_geiq else {"subject_to_iae_rules": True}
        from_company_kwargs = {
            "brand": "Black Mesa",
            "description": "Working to make a better tomorrow for all mankind",
            "phone": "0601020304",
            "with_jobs": True,
        } | company_kind_kwargs
        from_company = companies_factories.CompanyFactory(**from_company_kwargs)
        to_company = companies_factories.CompanyFactory(**company_kind_kwargs)

        if is_geiq:
            geiq_diag = eligibility_factories.GEIQEligibilityDiagnosisFactory(
                author=users_factories.EmployerFactory(membership__company=from_company),
                author_kind=eligibility_enums.AuthorKind.GEIQ,
                author_geiq=from_company,
            )
            geiq_assessment = AssessmentFactory(companies=[from_company])
        else:
            iae_diag = eligibility_factories.IAEEligibilityDiagnosisFactory(
                author=users_factories.EmployerFactory(membership__company=from_company),
                author_kind=eligibility_enums.AuthorKind.EMPLOYER,
                author_siae=from_company,
            )
            evaluated_siae = EvaluatedSiaeFactory(siae=from_company)
            prolongation_request = approvals_factories.ProlongationRequestFactory(declared_by_siae=from_company)
            prolongation = approvals_factories.ProlongationFactory(declared_by_siae=from_company)
            suspension = approvals_factories.SuspensionFactory(siae=from_company)

        sent_jobapp = JobApplicationFactory(sent_by_employer=True, sender_company=from_company)
        received_jobapp = JobApplicationFactory(sent_by_prescriber_alone=True, to_company=from_company)
        transferred_jobapp = JobApplicationFactory(sent_by_prescriber_alone=True, transferred_from=from_company)
        assignment = users_factories.JobSeekerAssignmentFactory(company=from_company)
        job_description = companies_factories.JobDescriptionFactory(company=from_company)
        active_membership = companies_factories.CompanyMembershipFactory(company=from_company)
        inactive_membership = companies_factories.CompanyMembershipFactory(company=from_company, is_active=False)
        invitation = invitations_factories.EmployerInvitationFactory(company=from_company)
        orientation = OrientationFactory(
            sender_kind=SenderKind.EMPLOYER, sender_company=from_company, sender_prescriber_organization=None
        )

        transfer.transfer_org_data(from_company, to_company, transfer.COMPANY_TRANSFER_FIELDS, disable_from_org)

        to_company.refresh_from_db()
        sent_jobapp.refresh_from_db()
        received_jobapp.refresh_from_db()
        transferred_jobapp.refresh_from_db()
        assignment.refresh_from_db()
        job_description.refresh_from_db()
        active_membership.refresh_from_db()
        inactive_membership.refresh_from_db()
        invitation.refresh_from_db()
        orientation.refresh_from_db()

        assert sent_jobapp.sender_company == to_company
        assert received_jobapp.to_company == to_company
        assert transferred_jobapp.transferred_from == to_company
        assert assignment.company == to_company
        assert job_description.company == to_company
        assert active_membership.company == to_company
        assert inactive_membership.company == to_company
        assert invitation.company == to_company
        assert orientation.sender_company == to_company
        assert to_company.brand == from_company.brand
        assert to_company.description == from_company.description
        assert to_company.phone == from_company.phone

        if is_geiq:
            geiq_diag.refresh_from_db()
            geiq_assessment.refresh_from_db()

            assert geiq_diag.author_geiq == to_company
            assertQuerySetEqual(geiq_assessment.companies.all(), [to_company])
        else:
            iae_diag.refresh_from_db()
            evaluated_siae.refresh_from_db()
            prolongation_request.refresh_from_db()
            prolongation.refresh_from_db()
            suspension.refresh_from_db()

            assert iae_diag.author_siae == to_company
            assert evaluated_siae.siae == to_company
            assert prolongation_request.declared_by_siae == to_company
            assert prolongation.declared_by_siae == to_company
            assert suspension.siae == to_company

        if disable_from_org:
            from_company.refresh_from_db()
            assert from_company.block_job_applications
            assert not from_company.is_searchable

    @pytest.mark.parametrize("disable_from_org", [False, True])
    def test_prescriberorg_transfer(self, disable_from_org):
        from_org = prescribers_factories.PrescriberOrganizationFactory(
            authorized=True,
            description="Description vraiment très intéressante",
            email="from_org@test.local",
            name="Presc. Org. 1",
            phone="0601020304",
            website="http://presc.org",
        )
        to_org = prescribers_factories.PrescriberOrganizationFactory(authorized=True)

        iae_diag = eligibility_factories.IAEEligibilityDiagnosisFactory(
            author_kind=eligibility_enums.AuthorKind.PRESCRIBER,
            author_prescriber_organization=from_org,
            author=users_factories.PrescriberFactory(membership__organization=from_org),
        )
        geiq_diag = eligibility_factories.GEIQEligibilityDiagnosisFactory(
            author_kind=eligibility_enums.AuthorKind.PRESCRIBER,
            author_prescriber_organization=from_org,
            author=users_factories.PrescriberFactory(membership__organization=from_org),
        )
        sent_jobapp = JobApplicationFactory(sent_by_prescriber=True, sender_prescriber_organization=from_org)
        assignment = users_factories.JobSeekerAssignmentFactory(prescriber_organization=from_org)
        active_membership = prescribers_factories.PrescriberMembershipFactory(organization=from_org)
        inactive_membership = prescribers_factories.PrescriberMembershipFactory(organization=from_org, is_active=False)
        invitation = invitations_factories.PrescriberWithOrgInvitationFactory(organization=from_org)
        orientation = OrientationFactory(sender_prescriber_organization=from_org)
        prolongation_request = approvals_factories.ProlongationRequestFactory(prescriber_organization=from_org)
        prolongation = approvals_factories.ProlongationFactory(prescriber_organization=from_org)

        transfer.transfer_org_data(from_org, to_org, transfer.PRESCRIBERORG_TRANSFER_FIELDS, disable_from_org)

        to_org.refresh_from_db()
        iae_diag.refresh_from_db()
        geiq_diag.refresh_from_db()
        sent_jobapp.refresh_from_db()
        assignment.refresh_from_db()
        active_membership.refresh_from_db()
        inactive_membership.refresh_from_db()
        invitation.refresh_from_db()
        orientation.refresh_from_db()
        prolongation_request.refresh_from_db()
        prolongation.refresh_from_db()

        assert iae_diag.author_prescriber_organization == to_org
        assert geiq_diag.author_prescriber_organization == to_org
        assert sent_jobapp.sender_prescriber_organization == to_org
        assert assignment.prescriber_organization == to_org
        assert active_membership.organization == to_org
        assert inactive_membership.organization == to_org
        assert invitation.organization == to_org
        assert orientation.sender_prescriber_organization == to_org
        assert prolongation_request.prescriber_organization == to_org
        assert prolongation.prescriber_organization == to_org
        assert to_org.description == from_org.description
        assert to_org.email == from_org.email
        assert to_org.name == from_org.name
        assert to_org.phone == from_org.phone
        assert to_org.website == from_org.website

        if disable_from_org:
            from_org.refresh_from_db()
            assert not from_org.is_searchable

    @pytest.mark.parametrize(
        "from_org_factory",
        [
            companies_factories.CompanyWith2MembershipsFactory,
            prescribers_factories.PrescriberOrganizationWith2MembershipFactory,
        ],
    )
    def test_disable_from_org(self, from_org_factory):
        from_org = from_org_factory()
        if isinstance(from_org, companies_models.Company):
            to_org = companies_factories.CompanyFactory(kind=from_org.kind)
        else:
            to_org = prescribers_factories.PrescriberOrganizationFactory()

        with freeze_time() as frozen_now:
            transfer.transfer_org_data(
                from_org,
                to_org,
                transfer.MODEL_TRANSFER_FIELDS[from_org.__class__] - {transfer.TransferField.MEMBERSHIPS},
                True,
            )

        from_org.refresh_from_db()

        for membership in from_org.memberships.all():
            assert not membership.is_active

        if isinstance(from_org, companies_models.Company):
            assert from_org.block_job_applications
            assert from_org.job_applications_blocked_at == frozen_now().replace(tzinfo=datetime.UTC)

    def test_transfer_job_seeker_assignments(self):
        membership = companies_factories.CompanyMembershipFactory()
        from_company = membership.company
        employer = membership.user
        to_company = companies_factories.CompanyFactory()

        # Assignment without similar assignment in the other organization
        assignment_1 = users_factories.JobSeekerAssignmentFactory(
            professional=employer,
            company=from_company,
            last_action_kind=users_enums.ActionKind.IAE_ELIGIBILITY,
        )
        # Assignment with a similar assignment in the other org but older
        assignment_2 = users_factories.JobSeekerAssignmentFactory(
            professional=employer,
            company=from_company,
            last_action_kind=users_enums.ActionKind.CREATE,
        )
        assignment_2_to_comp = users_factories.JobSeekerAssignmentFactory(
            job_seeker=assignment_2.job_seeker,
            professional=assignment_2.professional,
            company=to_company,
            last_action_kind=users_enums.ActionKind.APPLY,
        )
        # Assignment with a similar assignment in the other org but more recent
        assignment_3_to_comp = users_factories.JobSeekerAssignmentFactory(
            professional=employer,
            company=to_company,
            last_action_kind=users_enums.ActionKind.CREATE,
        )
        assignment_3 = users_factories.JobSeekerAssignmentFactory(
            job_seeker=assignment_3_to_comp.job_seeker,
            professional=assignment_3_to_comp.professional,
            company=from_company,
            last_action_kind=users_enums.ActionKind.APPLY,
        )

        assert users_models.JobSeekerAssignment.objects.count() == 5

        transfer.transfer_org_data(from_company, to_company, transfer.COMPANY_TRANSFER_FIELDS, True)

        updated_assignment_1 = users_models.JobSeekerAssignment.objects.get(pk=assignment_1.pk)
        updated_assignment_2_to_comp = users_models.JobSeekerAssignment.objects.get(pk=assignment_2_to_comp.pk)
        updated_assignment_3_to_comp = users_models.JobSeekerAssignment.objects.get(pk=assignment_3_to_comp.pk)
        assert users_models.JobSeekerAssignment.objects.count() == 3
        assert updated_assignment_1.company_id == to_company.pk
        assert updated_assignment_1.created_at == assignment_1.created_at
        assert updated_assignment_1.last_action_kind == users_enums.ActionKind.IAE_ELIGIBILITY
        assert updated_assignment_1.last_action_at == assignment_1.last_action_at
        assert not users_models.JobSeekerAssignment.objects.filter(pk=assignment_2.pk).exists()
        assert updated_assignment_2_to_comp.company_id == to_company.pk
        assert updated_assignment_2_to_comp.created_at == assignment_2.created_at
        assert updated_assignment_2_to_comp.last_action_kind == users_enums.ActionKind.APPLY
        assert updated_assignment_2_to_comp.last_action_at == assignment_2_to_comp.last_action_at
        assert not users_models.JobSeekerAssignment.objects.filter(pk=assignment_3.pk).exists()
        assert updated_assignment_3_to_comp.company_id == to_company.pk
        assert updated_assignment_3_to_comp.created_at == assignment_3_to_comp.created_at
        assert updated_assignment_3_to_comp.last_action_kind == users_enums.ActionKind.APPLY
        assert updated_assignment_3_to_comp.last_action_at == assignment_3.last_action_at

    def test_transfer_geiq_assessments(self):
        from_company = companies_factories.CompanyFactory(kind=companies_enums.CompanyKind.GEIQ)
        to_company = companies_factories.CompanyFactory(kind=companies_enums.CompanyKind.GEIQ)
        assessment = AssessmentFactory(companies=[from_company])

        transfer.transfer_org_data(from_company, to_company, transfer.COMPANY_TRANSFER_FIELDS, True)

        assessment.refresh_from_db()
        assertQuerySetEqual(assessment.companies.all(), [to_company])

        # Check case where two GEIQ companies are part of the same assessment
        assessment2 = AssessmentFactory(companies=[from_company, to_company])

        transfer.transfer_org_data(from_company, to_company, transfer.COMPANY_TRANSFER_FIELDS, True)

        assessment2.refresh_from_db()
        assertQuerySetEqual(assessment2.companies.all(), [to_company])
        assertQuerySetEqual(to_company.assessments.all(), [assessment, assessment2], ordered=False)
