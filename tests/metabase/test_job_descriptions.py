import pytest
from freezegun import freeze_time

from itou.metabase.tables.job_descriptions import TABLE
from itou.siaes.models import SiaeJobDescription
from tests.jobs.factories import create_test_romes_and_appellations
from tests.siaes.factories import SiaeJobDescriptionFactory


@freeze_time("2023-06-21T10:44:24.401Z")
@pytest.mark.django_db
def test_job_description_metabase_fields():
    create_test_romes_and_appellations(["M1805"], appellations_per_rome=3)
    obj = SiaeJobDescriptionFactory(is_active=False)
    obj = SiaeJobDescription.objects.get(pk=obj.pk)
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
