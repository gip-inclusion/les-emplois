import factory
from faker import Faker

from itou.rdv_insertion.enums import InvitationStatus, InvitationType
from itou.rdv_insertion.models import Invitation, InvitationRequest
from itou.users.enums import Title
from tests.companies.factories import CompanyFactory
from tests.users.factories import JobSeekerFactory


fake = Faker("fr_FR")


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
                "id": invitation.rdv_insertion_invitation_id,
                "format": invitation.type,
                "clicked": False,
                "rdv_with_referents": False,
                "created_at": obj.created_at.isoformat(),
                "motif_category": {
                    "id": 1,
                    "short_name": "siae_interview",
                    "name": "Entretien SIAE",
                },
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
        with_sms_invitation = factory.Trait(
            job_seeker__phone="0600000000",
            sms_invitation=factory.RelatedFactory(
                "tests.rdv_insertion.factories.InvitationFactory",
                factory_related_name="invitation_request",
                type=InvitationType.SMS,
            ),
            set_api_response=factory.PostGeneration(set_api_response),
        )

    job_seeker = factory.SubFactory(JobSeekerFactory)
    company = factory.SubFactory(CompanyFactory, with_membership=True)
    email_invitation = factory.RelatedFactory(
        "tests.rdv_insertion.factories.InvitationFactory",
        factory_related_name="invitation_request",
        type=InvitationType.EMAIL,
    )
    rdv_insertion_user_id = factory.LazyAttribute(lambda o: o.job_seeker.pk + 100)
    api_response = {}

    set_api_response = factory.PostGeneration(set_api_response)


class InvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Invitation

    type = factory.Faker("random_element", elements=InvitationType.values)
    status = factory.Faker("random_element", elements=InvitationStatus.values)
    rdv_insertion_invitation_id = factory.Sequence(lambda n: n + 4000)
