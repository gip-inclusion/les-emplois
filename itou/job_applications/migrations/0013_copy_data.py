import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import itou.utils.validators


def copy_data(apps, schema_editor):

    JobApplication = apps.get_model("job_applications", "JobApplication")
    SiaeJobDescription = apps.get_model("siaes", "SiaeJobDescription")

    for job_application in JobApplication.objects.all():

        for job in job_application.jobs.all():

            try:
                job_description = job_application.to_siae.job_description_through.get(
                    appellation=job
                )
            except SiaeJobDescription.DoesNotExist:
                continue
            job_application.selected_jobs.add(job_description)
            job_application.save()


class Migration(migrations.Migration):

    dependencies = [("job_applications", "0012_jobapplication_selected_jobs")]

    operations = [migrations.RunPython(copy_data, migrations.RunPython.noop)]
