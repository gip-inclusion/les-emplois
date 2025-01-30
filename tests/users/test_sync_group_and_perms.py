import itertools

from django.contrib.auth.models import Group
from django.core.management import call_command

from itou.users.management.commands import sync_group_and_perms


def test_command(snapshot, caplog):
    call_command("sync_group_and_perms")
    assert caplog.messages[:-1] == snapshot(name="logs")
    assert caplog.messages[-1].startswith(
        "Management command itou.users.management.commands.sync_group_and_perms succeeded in"
    )
    assert Group.objects.all().count() == len(sync_group_and_perms.get_permissions_dict())

    for group in Group.objects.all():
        assert [perm.codename for perm in group.permissions.all()] == snapshot(name=group.name)


def test_readonly_group():
    permissions = sync_group_and_perms.get_permissions_dict()
    readonly_groups = {name for name in permissions.keys() if name.endswith("-readonly")}
    for group in readonly_groups:
        assert set(permissions[group].keys()) == set(permissions[group.replace("-readonly", "")].keys())
        assert set(itertools.chain(*permissions[group].values())) == {"view"}
