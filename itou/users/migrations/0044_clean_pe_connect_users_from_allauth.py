from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0043_prevent_pe_connect_duplicates"),
    ]

    operations = [migrations.RunSQL("TRUNCATE socialaccount_socialaccount, socialaccount_socialtoken", elidable=True)]
