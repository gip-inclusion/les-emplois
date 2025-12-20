from django.urls import reverse
from pytest_django.asserts import assertContains

from itou.nexus.models import NexusMembership, NexusStructure, NexusUser
from tests.nexus.factories import NexusMembershipFactory, NexusRessourceSyncStatusFactory


def test_old_objects_are_displayed(admin_client):
    membership = NexusMembershipFactory()
    user = membership.user
    structure = membership.structure

    NexusRessourceSyncStatusFactory(service=user.source)

    # The default manager doesn't see the instances
    for model in [NexusUser, NexusMembership, NexusStructure]:
        assert model.objects.count() == 0

    response = admin_client.get(reverse("admin:nexus_nexususer_change", kwargs={"object_id": user.pk}))
    assert response.status_code == 200
    assertContains(response, membership.pk)  # The membership inline also works
    response = admin_client.get(reverse("admin:nexus_nexusstructure_change", kwargs={"object_id": structure.pk}))
    assert response.status_code == 200
    assertContains(response, membership.pk)  # The membership inline also works
    response = admin_client.get(reverse("admin:nexus_nexusmembership_change", kwargs={"object_id": membership.pk}))
    assert response.status_code == 200
