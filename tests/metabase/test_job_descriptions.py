import pytest
from freezegun import freeze_time

from itou.companies.models import JobDescription
from itou.metabase.tables.job_descriptions import TABLE
from tests.companies.factories import JobDescriptionFactory
from tests.jobs.factories import create_test_romes_and_appellations


@freeze_time("2023-06-21T10:44:24.401Z")
@pytest.mark.django_db
def test_job_description_metabase_fields():
    create_test_romes_and_appellations(["M1805"], appellations_per_rome=3)
    obj = JobDescriptionFactory(is_active=False)
    obj = JobDescription.objects.get(pk=obj.pk)
    obj.is_active = True
    obj.save()
    obj.refresh_from_db()
    assert TABLE.get(column_name="mises_a_jour_champs", input=obj) == [
        {
            "at": "2023-06-21T10:44:24.401Z",
            "field": "is_active",
            "from": False,
            "to": True,
        }
    ]
