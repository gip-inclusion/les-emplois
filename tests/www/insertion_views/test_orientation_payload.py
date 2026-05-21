from itou.www.insertion_views.orientation import build_dora_orientation_payload
from tests.insertion.factories import ServiceFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory


def test_build_dora_orientation_payload(db):
    organization = PrescriberOrganizationFactory(siret="12345678901234")
    prescriber = PrescriberFactory(membership=True, membership__organization=organization, phone="0142030405")
    job_seeker = JobSeekerFactory(
        first_name="Boris",
        last_name="Baracus",
        email="boris@example.org",
        phone="0102030405",
        jobseeker_profile__pole_emploi_id="12345678901",
    )
    service = ServiceFactory(uid="soliguide--svc-1")

    payload = build_dora_orientation_payload(
        service=service,
        job_seeker=job_seeker,
        referent_data={
            "referent_first_name": "Hannibal",
            "referent_last_name": "Smith",
            "referent_email": "hannibal@example.org",
            "referent_phone": "0506070809",
            "orientation_reason": "Besoin d'accompagnement vers l'emploi",
        },
        documents_data={
            "gdpr_consent": True,
            "credentials_documents_files": [{"key": "local/#orientations/aB3x/doc.pdf"}],
            "credentials_proof_files": [{"key": "local/#orientations/aB3x/proof.pdf"}],
        },
        prescriber=prescriber,
        organization=organization,
    )

    assert payload == {
        "di_service_id": "soliguide--svc-1",
        "beneficiary_first_name": "Boris",
        "beneficiary_last_name": "Baracus",
        "beneficiary_email": "boris@example.org",
        "beneficiary_phone": "0102030405",
        "beneficiary_france_travail_number": "12345678901",
        "referent_first_name": "Hannibal",
        "referent_last_name": "Smith",
        "referent_email": "hannibal@example.org",
        "referent_phone": "0506070809",
        "orientation_reasons": "Besoin d'accompagnement vers l'emploi",
        "data_protection_commitment": True,
        "beneficiary_attachments": [
            "local/#orientations/aB3x/doc.pdf",
            "local/#orientations/aB3x/proof.pdf",
        ],
        "emplois_data": {
            "beneficiary_id": str(job_seeker.public_id),
            "structure_id": str(organization.uid),
            "structure_name": organization.name,
            "structure_siret": "12345678901234",
            "prescriber_id": str(prescriber.public_id),
            "prescriber_email": prescriber.email,
            "prescriber_first_name": prescriber.first_name,
            "prescriber_last_name": prescriber.last_name,
            "prescriber_phone": "0142030405",
        },
    }
