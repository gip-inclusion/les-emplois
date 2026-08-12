import pytest

from tests.insertion.factories import OrientationFactory, OrientationProcessLinkFactory


def test_new_orientation_for_structure(snapshot):
    link = OrientationProcessLinkFactory(orientation__for_snapshot=True)
    email = link.email_orientation_new_for_structure

    assert email.to == [link.orientation.service.contact_email]
    assert email.subject == snapshot(name="subject")
    body = email.body.replace(str(link.pk), "[PK of OrientationProcessLink]")
    assert body == snapshot(name="body")


@pytest.mark.parametrize(
    "contact_full_name,contact_phone",
    [("", ""), ("Jean Dupont", "0102030405")],
    ids=["minimum_contact_info", "maximum_contact_info"],
)
def test_new_orientation_for_referent(snapshot, contact_full_name, contact_phone):
    orientation = OrientationFactory(
        for_snapshot=True, service__contact_full_name=contact_full_name, service__contact_phone=contact_phone
    )
    email = orientation.email_orientation_new_for_referent

    assert email.to == [orientation.referent_email]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
