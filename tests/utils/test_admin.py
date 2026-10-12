import datetime
import glob
import importlib
import os.path

import factory
import pytest
from allauth.account.models import EmailAddress
from django.apps import apps
from django.conf import settings
from django.contrib.admin import ModelAdmin
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user, models as auth_models
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from itou.antivirus.models import Scan
from itou.api.models import CompanyToken, DepartmentToken, ServiceToken
from itou.approvals.models import Approval, ApprovalQuerySet
from itou.asp.models import Department
from itou.cities.models import DirectoryActiveCity
from itou.companies.models import SiaeACIConvergencePHC
from itou.emails.models import Email
from itou.geiq_assessments.models import LabelInfos
from itou.insertion import models as insertion_models
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationTransitionLog
from itou.users.models import NirModificationRequest
from itou.utils.admin import (
    EfficientDateHierarchyAdminMixin,
    EfficientDateHierarchyQuerySetMixin,
    with_efficient_date_hierarchy,
)
from tests.approvals.factories import ApprovalFactory
from tests.cities.factories import create_city_guerande
from tests.companies.factories import SiaeFinancialAnnexFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import AssessmentCampaignFactory
from tests.geo.factories import create_qpv
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWith2MembershipFactory,
)
from tests.invitations.factories import LaborInspectorInvitationFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.nexus.factories import NexusRessourceSyncStatusFactory
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedJobApplicationSanctionFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
    SanctionsFactory,
)
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    ProfessionalFactory,
    UserFactory,
)


def get_all_subclasses(cls):
    for subclass in cls.__subclasses__():
        yield from get_all_subclasses(subclass)
        yield subclass


def get_all_factories():
    # Make sure all factories are loaded
    for item in glob.glob("**/factories.py", root_dir=os.path.join(settings.ROOT_DIR, "tests")):
        importlib.import_module(f"tests.{item.removesuffix('.py').replace('/', '.')}")

    return set(get_all_subclasses(factory.django.DjangoModelFactory))


# The admin pages take a while to render: spread them over several pytest-xdist workers
ADMIN_SHARDS = 4


@pytest.mark.parametrize("shard", range(ADMIN_SHARDS))
def test_all_admin(admin_client, mocker, subtests, shard):
    """Test that all admin pages load without error."""
    mocker.patch("itou.utils.throttling.FailSafeUserRateThrottle.rate", "10000/minute")  # Avoid rate limiting

    admin_registered_models = {model for model in apps.get_models() if admin_site.is_registered(model)}

    response = admin_client.get("/admin/")
    assert response.status_code == 200

    # Create some data for models without factories
    admin_user = get_user(admin_client)
    DirectoryActiveCity.objects.create(city=create_city_guerande())
    create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
    auth_models.Group.objects.create(name="Groupe de test")
    CompanyToken.objects.create(label="Test")
    SiaeACIConvergencePHC.objects.create(siret="12345678900012")
    ServiceToken.objects.create(service="dora")
    DepartmentToken.objects.create(department="01", label="Token tests département 01")
    Scan.objects.create(file=FileFactory(), clamav_signature="toto")
    Department.objects.create(code="33", name="Gironde", start_date=timezone.localdate())
    Token.objects.create(user=admin_user)
    ItouTOTPDeviceFactory(user=admin_user)
    EmailAddress.objects.create(user=admin_user, email="foobar@example.com", primary=False, verified=False)
    Email.objects.create(
        to=["foobar@example.com"],
        cc=[],
        bcc=[],
        subject="Hi",
        body_text="Hello",
        body_html="<html><body>Bonjour",
    )
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
        job_application=JobApplicationFactory(sent_by_prescriber_alone=True, job_seeker=job_seeker),
        to_state=JobApplicationState.PROCESSING,
    )
    # Insertion App
    source = insertion_models.GenericReferenceItem.objects.create(
        source=insertion_models.GenericReferenceItemSource.DATA_INCLUSION,
        kind=insertion_models.GenericReferenceItemKind.SOURCE,
        value="dora",
        label="DORA",
    )
    structure = insertion_models.Structure.objects.create(
        uid="dora--structure-uid",
        source=source,
        siret="12345678900012",
        name="Structure DORA",
        updated_on="2000-01-01",
    )
    insertion_models.Service.objects.create(
        uid="dora--service-uid",
        source=source,
        structure=structure,
        name="Service DORA",
        description="Description service DORA",
        updated_on="2000-01-01",
    )

    # Call factories that need parameters
    create_qpv("QP093028")
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
            SanctionsFactory,  # Called by EvaluatedJobApplicationSanctionFactory
            SiaeFinancialAnnexFactory,  # Called by SiaeConventionFactory
            UserFactory,  # A user was created with JobSeekerFactory
            ProfessionalFactory,  # A user was created with JobSeekerFactory
            PrescriberFactory,  # A user was created with JobSeekerFactory
            EmployerFactory,  # A user was created with JobSeekerFactory
            LaborInspectorFactory,  # A user was created with JobSeekerFactory
        ):
            continue
        factory_class()

    # Test all admin pages for the registered models of this shard
    # shard 0 gets models 0, 4, 8, …, shard 1 gets 1, 5, 9, …, and so on
    for model in sorted(admin_registered_models, key=lambda model: model._meta.label)[shard::ADMIN_SHARDS]:
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


class TestEfficientDateHierarchy:
    CREATED_AT_LIST = [
        datetime.datetime(2022, 6, 15, 10, 0),
        # Nothing in 2023
        datetime.datetime(2024, 12, 31, 23, 30),
        datetime.datetime(2025, 1, 1, 0, 30),  # Still 2024 in UTC (periods must be computed in local time)
        datetime.datetime(2026, 1, 20, 9, 0),
        # Nothing in Feb-Jun 2026
        datetime.datetime(2026, 7, 8, 12, 0),
        datetime.datetime(2026, 7, 16, 0, 15),  # Still July 15th in UTC (periods must be computed in local time)
        # Nothing in Aug-Sept 2026
        datetime.datetime(2026, 10, 12, 10, 0),
    ]

    @pytest.fixture(autouse=True)
    def approvals_over_time(self):
        for created_at in self.CREATED_AT_LIST:
            created_at = timezone.make_aware(created_at)
            ApprovalFactory(created_at=created_at, start_at=created_at.date(), origin_pe_approval=True)

    @pytest.mark.parametrize("order", ["ASC", "DESC"])
    @pytest.mark.parametrize(
        "kind,lookups,expected",
        [
            ("year", {}, [2022, 2024, 2025, 2026]),
            ("month", {"year": 2026}, [1, 7, 10]),
            ("day", {"year": 2026, "month": 7}, [8, 16]),
        ],
        ids=["year", "month", "day"],
    )
    @pytest.mark.parametrize(
        "method,field_name", [("datetimes", "created_at"), ("dates", "start_at")], ids=["datetimes", "dates"]
    )
    def test_periods(self, method, field_name, kind, lookups, expected, order):
        queryset = Approval.objects.filter(**{f"{field_name}__{lookup}": value for lookup, value in lookups.items()})

        periods = getattr(with_efficient_date_hierarchy(queryset), method)(field_name, kind, order=order)

        assert [getattr(period, kind) for period in periods] == (expected[::-1] if order == "DESC" else expected)
        assert periods == list(getattr(queryset, method)(field_name, kind, order=order))

    def test_num_queries(self, django_assert_num_queries):
        queryset = with_efficient_date_hierarchy(Approval.objects.all())

        with django_assert_num_queries(1):  # MIN and MAX only, there is no row
            assert queryset.filter(start_at__year=2030).dates("start_at", "year") == []
        with django_assert_num_queries(2):  # MIN and MAX, then a single query checking all the periods
            assert [period.year for period in queryset.dates("start_at", "year")] == [2022, 2024, 2025, 2026]

    def test_admin_mixin(self):
        class EfficientApprovalAdmin(EfficientDateHierarchyAdminMixin, ModelAdmin):
            pass

        queryset = EfficientApprovalAdmin(Approval, admin_site).get_queryset(RequestFactory().get("/"))

        assert isinstance(queryset, EfficientDateHierarchyQuerySetMixin)
        # The model's QuerySet methods are kept (they are used by list filters), and chaining keeps the mixin
        assert isinstance(queryset, ApprovalQuerySet)
        assert isinstance(queryset.valid(), EfficientDateHierarchyQuerySetMixin)
