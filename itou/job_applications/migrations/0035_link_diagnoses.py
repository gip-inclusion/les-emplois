"""
This migration has been deactivated after its first run.
We had to do it because adding new migrations to the User application
was breaking this one.
Anyway, it was made to migrate data so running it twice is useless.

----

After this migration (as of 2021-06-24) there are 287 cases for which
no diagnosis is found. Here is a way to retrieve the job applications
concerned:

# Hired without PASS IAE but no diagnosis => 254
# ----------------------------------------------

JobApplication.objects.filter(
    state="accepted",
    to_siae__kind__in=SIAE_WITH_CONVENTION_KINDS,
    approval__isnull=True,
    eligibility_diagnosis__isnull=True,
    hiring_without_approval=True,
).count()

# Hired with PASS IAE but no diagnosis => 1
# -----------------------------------------

JobApplication.objects.filter(
    state="accepted",
    to_siae__kind__in=SIAE_WITH_CONVENTION_KINDS,
    approval__isnull=True,
    eligibility_diagnosis__isnull=True,
    hiring_without_approval=False,
).count()

# PASS IAE that originates from itou (99999…) without diagnosis => 32
# -------------------------------------------------------------------

JobApplication.objects.filter(
    state="accepted",
    to_siae__kind__in=SIAE_WITH_CONVENTION_KINDS,
    approval__number__startswith=Approval.ASP_ITOU_PREFIX,
    eligibility_diagnosis__isnull=True,
    hiring_without_approval=False,
).count()
"""
from django.db import migrations


# Use imports (application defined models) instead of `apps.get_model()`
# (migration defined models). This can bite us later e.g. when running
# tests in a fresh database that runs all migrations again and again.
# However, we really need access to Managers, QuerySets and properties.
# from itou.eligibility.models import EligibilityDiagnosis
# from itou.job_applications.models import JobApplication


def move_data_forward(apps, schema_editor):
    """
    Link eligibility diagnoses to job applications.
    """

    # print("\n")
    # print("-" * 80)
    # print("Warning: this data migration will take a bunch of minutes on a production database.")
    # print("-" * 80)

    # job_applications_qs = (
    #     JobApplication.objects.filter(state="accepted")
    #     .select_related("approval", "job_seeker", "to_siae")
    #     .iterator(chunk_size=500)
    # )

    # for job_application in job_applications_qs:

    #     if not job_application.to_siae.is_subject_to_eligibility_rules:
    #         continue

    #     before = job_application.updated_at
    #     job_seeker = job_application.job_seeker

    #     qs = (
    #         EligibilityDiagnosis.objects.for_job_seeker(job_seeker)
    #         .filter(created_at__lte=before)
    #         .order_by("created_at")
    #     )

    #     # A diagnosis made by a prescriber has priority.
    #     eligibility_diagnosis = qs.by_author_kind_prescriber().last()

    #     if not eligibility_diagnosis:
    #         # Otherwise, use a diagnosis made by the SIAE ("auto-prescription").
    #         eligibility_diagnosis = qs.authored_by_siae(job_application.to_siae).last()

    #     if not eligibility_diagnosis:
    #         # Deals with cases from the past (when there was no rules).
    #         eligibility_diagnosis = qs.last()

    #     if not eligibility_diagnosis:

    #         if not job_application.approval and job_application.hiring_without_approval:
    #             # There are many applications with `hiring_without_approval=True` for which
    #             # the user has no diagnosis.
    #             # This is strange because the diagnosis is always made before an application
    #             # is accepted.
    #             # Perhaps at some point the SIAEs that did not want a PASS IAE did not have
    #             # to make a diagnosis…
    #             # We live with it for now.
    #             continue

    #         if not job_application.approval:
    #             print(f"{job_application.pk} - No diagnosis and no approval")
    #             continue

    #         if job_application.approval.originates_from_itou:
    #             print(f"{job_application.pk} - No diagnosis - {job_application.approval.number}")
    #             continue

    #     job_application.eligibility_diagnosis = eligibility_diagnosis
    #     job_application.save()
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("eligibility", "0005_auto_20200913_0532"),
        ("job_applications", "0034_jobapplication_eligibility_diagnosis"),
        ("users", "0025_create_index_upper_email"),
    ]

    operations = [migrations.RunPython(move_data_forward, migrations.RunPython.noop)]
