from django.utils import timezone

from itou.nexus.enums import Auth, NexusUserKind
from itou.nexus.utils import service_id
from itou.prescribers.models import PrescriberOrganization
from itou.utils.urls import get_absolute_url


def assert_user_equals(nexus_user, user, service):
    assert nexus_user.pk == service_id(service, user.pk)
    assert nexus_user.source == service
    assert nexus_user.source_kind == user.kind
    assert nexus_user.kind == NexusUserKind.FACILITY_MANAGER if user.is_employer else NexusUserKind.GUIDE
    assert nexus_user.auth == Auth.PRO_CONNECT
    for field in ["first_name", "last_name", "email", "phone"]:
        assert getattr(nexus_user, field) == getattr(user, field)
    assert nexus_user.last_login == user.last_login
    assert nexus_user.updated_at == timezone.now()


def assert_structure_equals(nexus_structure, structure, service):
    assert nexus_structure.id == service_id(service, structure.uid)
    assert nexus_structure.source == service
    assert nexus_structure.source_kind == structure.kind
    assert nexus_structure.name == getattr(structure, "display_name", structure.name)
    for field in [
        "siret",
        "email",
        "phone",
        "address_line_1",
        "address_line_2",
        "post_code",
        "city",
        "department",
        "website",
        "description",
    ]:
        assert getattr(nexus_structure, field) == getattr(structure, field)
    if isinstance(structure, PrescriberOrganization) and structure.is_authorized is False:
        assert nexus_structure.source_link == ""
    else:
        assert nexus_structure.source_link == get_absolute_url(structure.get_card_url())
