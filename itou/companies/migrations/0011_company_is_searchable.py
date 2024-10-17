from django.db import migrations, models


def forward(apps, editor):
    Company = apps.get_model("companies", "Company")

    Company.objects.filter(coords=None, geocoding_score=None).update(is_searchable=False)


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0010_remove_company_rdv_insertion_id_for_real"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="is_searchable",
            field=models.BooleanField(default=True, verbose_name="peut apparaître dans la recherche"),
        ),
        migrations.RunPython(forward, migrations.RunPython.noop, elidable=True),
    ]
