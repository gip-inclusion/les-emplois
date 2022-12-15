from itou.geo.factories import QPVFactory
from itou.geo.utils import coords_to_geometry
from itou.metabase.tables.utils import get_qpv_job_seeker_pks
from itou.users.factories import JobSeekerFactory


def test_get_qpv_job_seeker_pks():
    QPVFactory(code="QP093028")

    # Somewhere in QPV QP093028 (Aubervilliers)
    job_seeker_in_qpv = JobSeekerFactory(coords=coords_to_geometry("48.917735", "2.387311"))

    # Somewhere not in a QPV near Aubervilliers
    job_seeker_not_in_qpv = JobSeekerFactory(coords=coords_to_geometry("48.899", "2.412"))

    assert job_seeker_in_qpv.pk in get_qpv_job_seeker_pks()
    assert job_seeker_not_in_qpv.pk not in get_qpv_job_seeker_pks()
