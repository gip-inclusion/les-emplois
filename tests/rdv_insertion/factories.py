import datetime

import factory
from faker import Faker

from itou.rdv_insertion.models import Appointment, Invitation, InvitationRequest, Location, Participation, WebhookEvent
from itou.users.enums import Title
from itou.utils.mocks import rdv_insertion as rdvi_mocks
from tests.companies.factories import CompanyFactory
from tests.users.factories import JobSeekerUserFactory


fake = Faker("fr_FR")


DURATION_CHOICES = [
    datetime.timedelta(minutes=15),
    datetime.timedelta(minutes=25),
    datetime.timedelta(minutes=30),
    datetime.timedelta(minutes=45),
    datetime.timedelta(hours=1),
    datetime.timedelta(hours=1, minutes=30),
    datetime.timedelta(hours=2),
    datetime.timedelta(hours=2, minutes=30),
]


def set_api_response(obj, create, extracted, **kwargs):
    if not create:
        return

    obj.api_response = {
        "success": True,
        "user": {
            "id": obj.rdv_insertion_user_id,
            "uid": None,
            "affiliation_number": None,
            "role": "demandeur",
            "created_at": obj.created_at.isoformat(),
            "department_internal_id": None,
            "first_name": obj.job_seeker.first_name,
            "last_name": obj.job_seeker.last_name,
            "title": "madame" if obj.job_seeker.title == Title.MME else "monsieur",
            "address": obj.job_seeker.address_on_one_line,
            "phone_number": None,
            "email": obj.job_seeker.email,
            "birth_date": obj.job_seeker.jobseeker_profile.birthdate.isoformat(),
            "rights_opening_date": fake.date_this_year().isoformat(),
            "birth_name": None,
            "rdv_solidarites_user_id": obj.job_seeker.pk + 2000,
            "carnet_de_bord_carnet_id": None,
            "france_travail_id": obj.job_seeker.jobseeker_profile.pole_emploi_id,
            "referents": [],
        },
        "invitations": [
            {
                "id": invitation.rdv_insertion_id,
                "format": invitation.type,
                "clicked": False,
                "rdv_with_referents": False,
                "created_at": obj.created_at.isoformat(),
                "motif_category": {
                    "id": 1,
                    "short_name": "siae_interview",
                    "name": "Entretien SIAE",
                },
                "delivery_status": "delivered",
            }
            for invitation in obj.invitations.all()
        ],
    }
    obj.save(update_fields=["api_response"])


class InvitationRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InvitationRequest
        skip_postgeneration_save = True

    class Params:
        for_snapshot = factory.Trait(
            reason_category=InvitationRequest.ReasonCategory.SIAE_INTERVIEW,
            job_seeker__for_snapshot=True,
            company__for_snapshot=True,
            email_invitation__for_snapshot=True,
        )
        with_sms_invitation = factory.Trait(
            job_seeker__phone="0600000000",
            sms_invitation=factory.RelatedFactory(
                "tests.rdv_insertion.factories.InvitationFactory",
                factory_related_name="invitation_request",
                type=Invitation.Type.SMS,
            ),
            set_api_response=factory.PostGeneration(set_api_response),
        )

    job_seeker = factory.SubFactory(JobSeekerUserFactory)
    company = factory.SubFactory(CompanyFactory, with_membership=True)
    email_invitation = factory.RelatedFactory(
        "tests.rdv_insertion.factories.InvitationFactory",
        factory_related_name="invitation_request",
        type=Invitation.Type.EMAIL,
    )
    rdv_insertion_user_id = factory.LazyAttribute(lambda o: o.job_seeker.pk + 100)
    api_response = {}

    set_api_response = factory.PostGeneration(set_api_response)


class InvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Invitation

    class Params:
        for_snapshot = factory.Trait(
            type=Invitation.Type.EMAIL,
            status=Invitation.Status.DELIVERED,
            rdv_insertion_id=1234,
        )

    type = factory.Faker("random_element", elements=Invitation.Type.values)
    status = factory.Faker("random_element", elements=Invitation.Status.values)
    rdv_insertion_id = factory.Sequence(lambda n: n)


class LocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Location

    class Params:
        for_snapshot = factory.Trait(
            name="Salle de réunion",
            address="112 Quai de Jemmapes, 75010 Paris",
            phone_number="06 00 00 00 00",
            rdv_solidarites_id=1234,
        )

    name = factory.Faker("sentence")
    address = factory.Faker("address")
    phone_number = factory.Faker("phone_number")
    rdv_solidarites_id = factory.Sequence(lambda n: n)


class AppointmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Appointment

    class Params:
        for_snapshot = factory.Trait(
            status=Appointment.Status.UNKNOWN,
            start_at=datetime.datetime(2024, 8, 6, 8, 0, tzinfo=datetime.UTC),
            reason_category=Appointment.ReasonCategory.SIAE_INTERVIEW,
            reason="Entretien d'embauche",
            address="112 Quai de Jemmapes, 75010 Paris",
            duration=DURATION_CHOICES[0],
            rdv_insertion_id=1234,
            company__for_snapshot=True,
            location__for_snapshot=True,
        )
        revoked = factory.Trait(
            status=Appointment.Status.REVOKED,
            canceled_at=factory.Faker("past_datetime", start_date="-15d"),
        )
        seen = factory.Trait(
            status=Appointment.Status.SEEN,
            start_at=factory.Faker("past_datetime", start_date="-30d"),
        )
        collective = factory.Trait(
            is_collective=True,
            total_participants=factory.Faker("pyint", min_value=0, max_value=5),
            max_participants=factory.Faker("pyint", min_value=5, max_value=10),
        )

    company = factory.SubFactory(CompanyFactory, with_membership=True)
    location = factory.SubFactory(LocationFactory)
    status = factory.Faker("random_element", elements=Appointment.Status.values)
    reason_category = factory.Faker("random_element", elements=Appointment.ReasonCategory.values)
    reason = factory.Faker("sentence")
    is_collective = False
    start_at = factory.Faker("future_datetime", end_date="+60d", tzinfo=datetime.UTC)
    duration = factory.Faker("random_element", elements=DURATION_CHOICES)
    address = factory.Faker("address")
    rdv_insertion_id = factory.Sequence(lambda n: n)


class ParticipationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Participation

    class Params:
        for_snapshot = factory.Trait(
            id="11111111-1111-1111-1111-111111111111",
            status=Participation.Status.UNKNOWN,
            rdv_insertion_user_id=1234,
            rdv_insertion_id=1234,
            appointment__for_snapshot=True,
            job_seeker__for_snapshot=True,
        )

    job_seeker = factory.SubFactory(JobSeekerUserFactory)
    appointment = factory.SubFactory(AppointmentFactory)
    status = factory.Faker("random_element", elements=Participation.Status.values)
    rdv_insertion_user_id = factory.Sequence(lambda n: n)
    rdv_insertion_id = factory.Sequence(lambda n: n)


class WebhookEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WebhookEvent

    class Params:
        for_appointment = factory.Trait(
            body=rdvi_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_BODY,
            headers=rdvi_mocks.RDV_INSERTION_WEBHOOK_APPOINTMENT_HEADERS,
        )

    body = rdvi_mocks.RDV_INSERTION_WEBHOOK_INVITATION_BODY
    headers = rdvi_mocks.RDV_INSERTION_WEBHOOK_INVITATION_HEADERS
    is_processed = factory.Faker("boolean", chance_of_getting_true=30)
