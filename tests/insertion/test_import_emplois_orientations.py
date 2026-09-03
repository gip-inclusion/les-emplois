import json
import uuid

from django.core.management import call_command

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from itou.job_applications.enums import SenderKind
from tests.companies.factories import CompanyFactory
from tests.insertion.factories import ServiceFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory, ProfessionalFactory


def _dora_entry(*, beneficiary, sender, organization, service, **overrides):
    """Build an entry as produced by Dora's `export_emplois_orientations`."""
    entry = {
        "status": OrientationStatus.PENDING,
        "processing_date": None,
        "creation_date": "2026-01-15T10:00:00+00:00",
        "beneficiary_contact_preferences": ["EMAIL"],
        "beneficiary_other_contact_method": "",
        "beneficiary_availability": "2026-02-01",
        "requirements": ["critère A"],
        "situation": ["situation B"],
        "situation_other": "",
        "referent_last_name": "Durand",
        "referent_first_name": "Alex",
        "referent_phone": "0102030405",
        "referent_email": "referent@example.com",
        "orientation_reasons": "un motif",
        "duration_weekly_hours": 20,
        "duration_weeks": 4,
        "data_protection_commitment": True,
        "beneficiary_attachments": ["orientations/attachment.pdf"],
        "service_id": service.uid,
        "emplois_sync_uid": str(uuid.uuid4()),
        "beneficiary_id": str(beneficiary.public_id),
        "prescriber_id": str(sender.public_id),
        "structure_id": str(organization.uid),
    }
    entry.update(overrides)
    return entry


def _write_export(tmp_path, entries):
    path = tmp_path / "export.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


def test_import_prescriber_orientation(tmp_path):
    beneficiary = JobSeekerFactory()
    sender = ProfessionalFactory()
    organization = PrescriberOrganizationFactory()
    service = ServiceFactory()
    entry = _dora_entry(beneficiary=beneficiary, sender=sender, organization=organization, service=service)
    export_file = _write_export(tmp_path, [entry])

    call_command("import_emplois_orientations", file=export_file, wet_run=True)

    orientation = Orientation.objects.get()
    assert str(orientation.id) == entry["emplois_sync_uid"]
    assert orientation.beneficiary == beneficiary
    assert orientation.sender == sender
    assert orientation.sender_kind == SenderKind.PRESCRIBER
    assert orientation.sender_prescriber_organization == organization
    assert orientation.sender_company is None
    assert orientation.service == service
    assert orientation.status == OrientationStatus.PENDING
    assert orientation.requirements == ["critère A"]
    assert orientation.attachments == ["orientations/attachment.pdf"]
    assert orientation.duration_weekly_hours == 20
    assert orientation.created_at.isoformat() == "2026-01-15T10:00:00+00:00"


def test_import_employer_orientation(tmp_path):
    beneficiary = JobSeekerFactory()
    sender = ProfessionalFactory()
    company = CompanyFactory()
    service = ServiceFactory()
    entry = _dora_entry(beneficiary=beneficiary, sender=sender, organization=company, service=service)
    export_file = _write_export(tmp_path, [entry])

    call_command("import_emplois_orientations", file=export_file, wet_run=True)

    orientation = Orientation.objects.get()
    assert orientation.sender_kind == SenderKind.EMPLOYER
    assert orientation.sender_company == company
    assert orientation.sender_prescriber_organization is None


def test_dry_run_creates_nothing(tmp_path):
    entry = _dora_entry(
        beneficiary=JobSeekerFactory(),
        sender=ProfessionalFactory(),
        organization=PrescriberOrganizationFactory(),
        service=ServiceFactory(),
    )
    export_file = _write_export(tmp_path, [entry])

    call_command("import_emplois_orientations", file=export_file)

    assert not Orientation.objects.exists()


def test_existing_orientation_is_left_untouched(tmp_path):
    beneficiary = JobSeekerFactory()
    sender = ProfessionalFactory()
    organization = PrescriberOrganizationFactory()
    service = ServiceFactory()
    entry = _dora_entry(beneficiary=beneficiary, sender=sender, organization=organization, service=service)
    existing = Orientation.objects.create(
        id=entry["emplois_sync_uid"],
        beneficiary=beneficiary,
        sender=sender,
        sender_kind=SenderKind.PRESCRIBER,
        sender_prescriber_organization=organization,
        service=service,
        referent_last_name="Original",
        referent_first_name="Original",
        referent_email="original@example.com",
    )
    export_file = _write_export(tmp_path, [entry])

    call_command("import_emplois_orientations", file=export_file, wet_run=True)

    existing.refresh_from_db()
    assert Orientation.objects.count() == 1
    assert existing.referent_last_name == "Original"


def test_missing_references_are_skipped(tmp_path, caplog):
    valid = _dora_entry(
        beneficiary=JobSeekerFactory(),
        sender=ProfessionalFactory(),
        organization=PrescriberOrganizationFactory(),
        service=ServiceFactory(),
    )
    # An unknown service: the entry must be skipped without aborting the import.
    unknown_service = _dora_entry(
        beneficiary=JobSeekerFactory(),
        sender=ProfessionalFactory(),
        organization=PrescriberOrganizationFactory(),
        service=ServiceFactory(),
    )
    unknown_service["service_id"] = "dora--does-not-exist"
    export_file = _write_export(tmp_path, [valid, unknown_service])

    call_command("import_emplois_orientations", file=export_file, wet_run=True)

    orientation = Orientation.objects.get()
    assert str(orientation.id) == valid["emplois_sync_uid"]
