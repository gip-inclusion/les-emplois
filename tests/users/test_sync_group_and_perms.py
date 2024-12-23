import io

from django.contrib.auth.models import Group
from django.core.management import call_command


def test_command(snapshot):
    stdout = io.StringIO()
    call_command("sync_group_and_perms", stdout=stdout)
    assert stdout.getvalue() == snapshot(name="stdout")
    assert Group.objects.all().count() == 2

    for group in Group.objects.all():
        assert [perm.codename for perm in group.permissions.all()] == snapshot(name=group.name)
