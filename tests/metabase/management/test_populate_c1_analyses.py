import datetime

import pytest
from django.core import management
from django.db import connection
from django.utils import timezone
from pytest_django.asserts import assertNumQueries

from itou.users.enums import UserKind
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


BASE_NUM_QUERIES = (
    1  # Count users rows
    + 1  # COMMIT Queryset counts (autocommit mode)
    + 1  # COMMIT Create table
    + 1  # Select all users elements ids (chunked_queryset)
    # 3 more queries here if there are some users
    + 1  # COMMIT (rename_table_atomically DROP TABLE)
    + 1  # COMMIT (rename_table_atomically RENAME TABLE)
    + 1  # COMMIT (rename_table_atomically DROP TABLE)
    + 1  # Count job_appication row
    + 1  # COMMIT Queryset counts (autocommit mode)
    + 1  # COMMIT Create table
    + 1  # Select all job_application elements ids (chunked_queryset)
    # 3 more queries here if there are some job applications
    + 1  # COMMIT (rename_table_atomically DROP TABLE)
    + 1  # COMMIT (rename_table_atomically RENAME TABLE)
    + 1  # COMMIT (rename_table_atomically DROP TABLE)
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_users():
    date_maj = datetime.date.today() + datetime.timedelta(days=-1)

    # First user
    #  - created by prescriber
    #  - logged_in recently
    user_1 = JobSeekerFactory(created_by=PrescriberFactory(), last_login=timezone.now(), first_login=timezone.now())
    # Second user
    #  - created by an employer
    user_2 = JobSeekerFactory(created_by=EmployerFactory())

    # Third user
    # - self created
    user_3 = JobSeekerFactory(last_login=timezone.now(), first_login=timezone.now() - datetime.timedelta(days=-1))

    with assertNumQueries(
        BASE_NUM_QUERIES
        + 1  # Select last user pk for current chunk
        + 1  # Select users chunk
        + 1  # COMMIT (inject_chunk)
    ):
        management.call_command("populate_c1_analyses")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_users ORDER BY id")
        rows = cursor.fetchall()

    assert rows == [
        (
            user_1.pk,
            UserKind.JOB_SEEKER,
            datetime.date.today(),
            datetime.date.today(),
            datetime.date.today(),
            "par prescripteur",
            date_maj,
        ),
        (
            user_2.pk,
            UserKind.JOB_SEEKER,
            datetime.date.today(),
            None,
            None,
            "par employeur",
            date_maj,
        ),
        (
            user_3.pk,
            UserKind.JOB_SEEKER,
            datetime.date.today(),
            datetime.date.today() - datetime.timedelta(days=-1),
            datetime.date.today(),
            "autonome",
            date_maj,
        ),
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_job_applications():
    date_maj = datetime.date.today() + datetime.timedelta(days=-1)
    ja = JobApplicationFactory(state="accepted")

    with assertNumQueries(
        BASE_NUM_QUERIES
        + 1  # Select last user pk for current chunk
        + 1  # Select users chunk
        + 1  # COMMIT (inject_chunk)
        + 1  # Select last job application pk for current chunk
        + 1  # Select job applcations chunk
        + 1  # COMMIT (inject_chunk)
    ):
        management.call_command("populate_c1_analyses")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_job_applications ORDER BY id")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows == [
            (
                ja.pk,
                ja.created_at.date(),
                ja.processed_at.date(),
                "Candidature acceptée",
                None,
                "default",
                "Orienteur sans organisation",
                ja.to_company.kind,
                date_maj,
            ),
        ]
