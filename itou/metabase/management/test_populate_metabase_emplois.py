import datetime

import pytest
from django.core import management
from django.db import connection

from itou.analytics.factories import DatumFactory


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("metabase")
def test_populate_metabase_analytics():
    date_maj = datetime.date.today() + datetime.timedelta(days=-1)
    data0 = DatumFactory(code="FOO-BAR", bucket="2021-12-31")
    data1 = DatumFactory(code="FOO-MAN", bucket="2020-10-17")
    data2 = DatumFactory(code="FOO-DUR", bucket="2022-08-16")
    management.call_command("populate_metabase_emplois", mode="analytics")
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM c1_analytics_v0 ORDER BY date")
        rows = cursor.fetchall()
        assert rows == [
            (
                str(data1.pk),
                "FOO-MAN",
                datetime.date(2020, 10, 17),
                data1.value,
                date_maj,
            ),
            (
                str(data0.pk),
                "FOO-BAR",
                datetime.date(2021, 12, 31),
                data0.value,
                date_maj,
            ),
            (
                str(data2.pk),
                "FOO-DUR",
                datetime.date(2022, 8, 16),
                data2.value,
                date_maj,
            ),
        ]
