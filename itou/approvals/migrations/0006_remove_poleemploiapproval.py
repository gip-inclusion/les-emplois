from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0005_delete_poleemploiapproval"),
    ]

    operations = [
        migrations.RunSQL("DROP TABLE approvals_poleemploiapproval"),
    ]
