from django.db import migrations

from itou.siae_evaluations import enums as evaluation_enums


def evaluated_job_application_state(job_app):
    # assuming the EvaluatedJobApplication instance is fully hydrated
    # with its evaluated_administrative_criteria before being called,
    # to prevent tons of additionnal queries in db.
    if len(job_app.evaluated_administrative_criteria.all()) == 0:
        return evaluation_enums.EvaluatedJobApplicationsState.PENDING

    if any(eval_admin_crit.proof_url == "" for eval_admin_crit in job_app.evaluated_administrative_criteria.all()):
        return evaluation_enums.EvaluatedJobApplicationsState.PROCESSING

    if any(
        eval_admin_crit.submitted_at is None for eval_admin_crit in job_app.evaluated_administrative_criteria.all()
    ):
        return evaluation_enums.EvaluatedJobApplicationsState.UPLOADED

    if any(
        eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        for eval_admin_crit in job_app.evaluated_administrative_criteria.all()
    ):
        return evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED

    if any(
        eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        for eval_admin_crit in job_app.evaluated_administrative_criteria.all()
    ):
        return evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2

    if any(
        eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        for eval_admin_crit in job_app.evaluated_administrative_criteria.all()
    ):
        return evaluation_enums.EvaluatedJobApplicationsState.REFUSED

    if all(
        eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        for eval_admin_crit in job_app.evaluated_administrative_criteria.all()
    ):
        return evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED


def set_final_reviewed_at(apps, schema_editor):
    EvaluationCampaign = apps.get_model("siae_evaluations", "EvaluationCampaign")
    EvaluatedSiae = apps.get_model("siae_evaluations", "EvaluatedSiae")

    for campaign in EvaluationCampaign.objects.exclude(ended_at=None).prefetch_related(
        "evaluated_siaes__evaluated_job_applications__evaluated_administrative_criteria"
    ):
        to_update = []
        for evaluated_siae in campaign.evaluated_siaes.all():
            if any(
                evaluated_job_application_state(job_app)
                in [
                    evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
                    evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
                ]
                for job_app in evaluated_siae.evaluated_job_applications.all()
            ):
                evaluated_siae.final_reviewed_at = campaign.ended_at
                to_update.append(evaluated_siae)
        EvaluatedSiae.objects.bulk_update(to_update, fields=["final_reviewed_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("siae_evaluations", "0009_evaluatedsiae_sanctioned_at"),
    ]

    operations = [migrations.RunPython(set_final_reviewed_at, elidable=True)]
