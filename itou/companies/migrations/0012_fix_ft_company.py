from django.db import migrations

import itou.companies.models


def forward(apps, editor):
    Company = apps.get_model("companies", "Company")

    Company.unfiltered_objects.filter(siret="13000548100010").update(
        is_searchable=True, active_members_email_reminder_last_sent_at=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0011_company_is_searchable"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="company",
            managers=[
                ("objects", itou.companies.models.CompanyManager()),
                ("unfiltered_objects", itou.companies.models.CompanyUnfilteredManager()),
            ],
        ),
        migrations.RunPython(forward, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
