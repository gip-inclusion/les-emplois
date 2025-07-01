
import pytest
from django.db import IntegrityError

from itou.users.models import User
from itou.utils.command import dry_runnable
from tests.users.factories import (
    JobSeekerFactory,
)


def test_dry_runnable_check_constraints():
    @dry_runnable
    def command(**kwargs):
        job_seeker = JobSeekerFactory()
        job_seeker.created_by_id = job_seeker.pk + 1
        job_seeker.save()

    assert User.objects.count() == 0
    with pytest.raises(IntegrityError, match="insert or update on table .* violates foreign key constraint"):
        command(wet_run=False)
    assert User.objects.count() == 0
