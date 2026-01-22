import glob
import importlib
import os.path

import factory
from allauth.account.models import EmailAddress
from django.apps import apps
from django.conf import settings
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user, models as auth_models
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.authtoken.models import Token

from itou.antivirus.models import Scan
from itou.api.models import CompanyToken, DepartmentToken, ServiceToken
from itou.asp.models import Department
from itou.companies.models import SiaeACIConvergencePHC
from itou.emails.models import Email
from itou.external_data.models import ExternalDataImport
from itou.geiq_assessments.models import LabelInfos
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationTransitionLog
from itou.nexus.enums import Service
from itou.nexus.models import ActivatedService
from itou.users.models import NirModificationRequest
from tests.cities.factories import create_city_guerande
from tests.companies.factories import SiaeFinancialAnnexFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import AssessmentCampaignFactory
from tests.geo.factories import QPVFactory
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
)
from tests.invitations.factories import LaborInspectorInvitationFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.nexus.factories import NexusRessourceSyncStatusFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedJobApplicationSanctionFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
    SanctionsFactory,
)
from tests.users.factories import EmployerFactory, JobSeekerFactory, UserFactory


def get_all_subclasses(cls):
    for subclass in cls.__subclasses__():
        yield from get_all_subclasses(subclass)
        yield subclass


def get_all_factories():
    # Make sure all factories are loaded
    for item in glob.glob("**/factories.py", root_dir=os.path.join(settings.ROOT_DIR, "tests")):
        importlib.import_module(f"tests.{item.removesuffix('.py').replace('/', '.')}")

    return set(get_all_subclasses(factory.django.DjangoModelFactory))


def test_all_admin(admin_client, mocker, subtests):
    """Test that all admin pages load without error."""
    mocker.patch("itou.utils.throttling.FailSafeUserRateThrottle.rate", "10000/minute")  # Avoid rate limiting

    admin_registered_models = {model for model in apps.get_models() if admin_site.is_registered(model)}

    response = admin_client.get("/admin/")
    assert response.status_code == 200

    # Create some data for models without factories
    admin_user = get_user(admin_client)
    create_city_guerande()
    create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
    auth_models.Group.objects.create(name="Groupe de test")
    CompanyToken.objects.create(label="Test")
    SiaeACIConvergencePHC.objects.create(siret="12345678900012")
    ServiceToken.objects.create(service="dora")
    DepartmentToken.objects.create(department="01", label="Token tests département 01")
    Scan.objects.create(file=FileFactory(), clamav_signature="toto")
    Department.objects.create(code="33", name="Gironde", start_date=timezone.localdate())
    Token.objects.create(user=admin_user)
    TOTPDevice.objects.create(user=admin_user, confirmed=False)
    EmailAddress.objects.create(user=admin_user, email="foobar@example.com", primary=False, verified=False)
    Email.objects.create(to=["foobar@example.com"], cc=[], bcc=[], subject="Hi", body_text="Hello")
    ExternalDataImport.objects.create(user=admin_user)
    evaluated_siae = EvaluatedAdministrativeCriteriaFactory().evaluated_job_application.evaluated_siae
    EvaluatedJobApplicationSanctionFactory(sanctions__evaluated_siae=evaluated_siae)
    InstitutionMembershipFactory(institution=evaluated_siae.evaluation_campaign.institution)
    LaborInspectorInvitationFactory(institution=evaluated_siae.evaluation_campaign.institution)
    LabelInfos.objects.create(campaign=AssessmentCampaignFactory(), data=[])
    job_seeker = JobSeekerFactory()
    NirModificationRequest.objects.create(
        jobseeker_profile=job_seeker.jobseeker_profile,
        requested_by=admin_user,
    )
    JobApplicationTransitionLog.objects.create(
        user=admin_user,
        job_application=JobApplicationFactory(job_seeker=job_seeker),
        to_state=JobApplicationState.PROCESSING,
    )
    ActivatedService.objects.create(user=EmployerFactory(), service=Service.PILOTAGE)

    # Call factories that need parameters
    QPVFactory(code="QP093028")
    GEIQEligibilityDiagnosisFactory(from_employer=True)
    IAEEligibilityDiagnosisFactory(from_employer=True)

    # Call this factory first as it might shadow other items if created later
    NexusRessourceSyncStatusFactory()

    # Call all factories to create at least one instance of each model with a factory
    for factory_class in get_all_factories():
        if factory_class._meta.model not in admin_registered_models:
            continue
        if factory_class in (
            AssessmentCampaignFactory,  # Already used above
            EvaluatedAdministrativeCriteriaFactory,  # Already used above
            EvaluatedJobApplicationFactory,  # Called by EvaluatedAdministrativeCriteriaFactory
            EvaluatedJobApplicationSanctionFactory,  # Already used above
            EvaluatedSiaeFactory,  # Called by EvaluatedAdministrativeCriteriaFactory
            EvaluationCampaignFactory,  # Called by EvaluatedAdministrativeCriteriaFactory
            FileFactory,  # Already used above
            GEIQEligibilityDiagnosisFactory,  # Already used above
            IAEEligibilityDiagnosisFactory,  # Already used above
            InstitutionFactory,  # Called by EvaluatedAdministrativeCriteriaFactory
            InstitutionMembershipFactory,  # Already used above
            InstitutionWith2MembershipFactory,  # No need
            JobApplicationFactory,  # Already used above
            JobSeekerFactory,  # Already used above
            LaborInspectorInvitationFactory,  # Already used above
            NexusRessourceSyncStatusFactory,  # Already used above
            QPVFactory,  # Already used above
            SanctionsFactory,  # Called by EvaluatedJobApplicationSanctionFactory
            SiaeFinancialAnnexFactory,  # Called by SiaeConventionFactory
            UserFactory,  # A lot of subfactories, no need to use it
        ):
            continue
        factory_class()

    # Test all admin pages for all registered models
    for model in admin_registered_models:
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        with subtests.test(model=f"{app_label}.{model_name}"):
            # List view
            url = reverse(f"admin:{app_label}_{model_name}_changelist")
            response = admin_client.get(url)
            assert response.status_code == 200

            # Add view
            url = reverse(f"admin:{app_label}_{model_name}_add")
            response = admin_client.get(url)
            assert response.status_code in (200, 403)  # Some models are not addable

            # Change view
            sample_objects = list(model.objects.order_by("?")[:3])
            assert sample_objects
            for obj in sample_objects:
                url = reverse(f"admin:{app_label}_{model_name}_change", args=(obj.pk,))
                response = admin_client.get(url)
                assert response.status_code == 200
