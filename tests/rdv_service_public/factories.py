import datetime

import factory
from django.utils import timezone

from itou.rdv_service_public.models import AppointmentProposal, OAuthToken
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory


class OAuthTokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OAuthToken

    user = factory.SubFactory(EmployerFactory)
    access_token = factory.Sequence(lambda n: f"access-token-{n}")
    refresh_token = factory.Sequence(lambda n: f"refresh-token-{n}")
    expires_at = factory.LazyFunction(lambda: timezone.now() + datetime.timedelta(hours=2))
    rdv_service_public_agent_id = factory.Sequence(int)


class AppointmentProposalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AppointmentProposal

    job_application = factory.SubFactory(JobApplicationFactory, sent_by_authorized_prescriber=True)
    company = factory.LazyAttribute(lambda proposal: proposal.job_application.to_company)
    job_seeker = factory.LazyAttribute(lambda proposal: proposal.job_application.job_seeker)
    created_by = factory.SubFactory(EmployerFactory)
    rdv_service_public_plan_id = factory.Sequence(int)
    rdv_service_public_user_id = factory.Sequence(int)
