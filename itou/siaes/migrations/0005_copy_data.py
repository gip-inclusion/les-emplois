import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import itou.utils.validators


def copy_data(apps, schema_editor):
    """
    Change Siae's primary key from `siret` to `id`
        [x] Step 1 - Create a NewSiae table where `siret` is not the PK. Add ForeignKeys too.
        [x] Step 2 - Populate NewSiae and its relations.
        [ ] Step 3 - Remove relations to Siae
        [ ] Step 4 - Delete Siae, rename "NewSiae" to "Siae", rename ForeignKeys from "new_siae" to "siae"
        [ ] Step 5 - Rename related_name from "new_job_description_through" to "job_description_through"
        [ ] Step 6 - Make FK to Siae non nullable
    """

    Siae = apps.get_model("siaes", "Siae")
    NewSiae = apps.get_model("siaes", "NewSiae")

    for siae in Siae.objects.all():

        if NewSiae.objects.filter(siret=siae.siret).exists():
            continue

        new_siae = NewSiae()
        new_siae.siret = siae.siret
        new_siae.naf = siae.naf
        new_siae.kind = siae.kind
        new_siae.name = siae.name
        new_siae.brand = siae.brand
        new_siae.phone = siae.phone
        new_siae.email = siae.email
        new_siae.website = siae.website
        new_siae.description = siae.description
        new_siae.address_line_1 = siae.address_line_1
        new_siae.address_line_2 = siae.address_line_2
        new_siae.post_code = siae.post_code
        new_siae.city = siae.city
        new_siae.department = siae.department
        new_siae.coords = siae.coords
        new_siae.geocoding_score = siae.geocoding_score
        new_siae.save()

    SiaeMembership = apps.get_model("siaes", "SiaeMembership")
    for membership in SiaeMembership.objects.all():
        membership.new_siae = NewSiae.objects.get(siret=membership.siae.siret)
        membership.save()

    SiaeJobDescription = apps.get_model("siaes", "SiaeJobDescription")
    for job_description in SiaeJobDescription.objects.all():
        job_description.new_siae = NewSiae.objects.get(siret=job_description.siae.siret)
        job_description.save()


class Migration(migrations.Migration):

    dependencies = [("siaes", "0004_auto_20191023_1325")]

    operations = [migrations.RunPython(copy_data, migrations.RunPython.noop)]
