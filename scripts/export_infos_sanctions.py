import csv

from itou.siae_evaluations import models
from itou.siaes.models import Siae


def export_lines_to_csv(filename, lines):
    with open(filename, "w", newline="") as csvfile:
        lines_writer = csv.writer(csvfile)
        for line in lines:
            lines_writer.writerow(line)


# List of sanctioned SIAE member emails
lines = []

for sanction in models.Sanctions.objects.filter(no_sanction_reason=""):
    evaluated = sanction.evaluated_siae
    for email in evaluated.siae.active_members.values_list("email", flat=True):
        lines.append(
            (
                evaluated.siae.pk,
                evaluated.siae.name,
                sanction.training_session,
                evaluated.notification_text,
                email,
            )
        )

export_lines_to_csv("/tmp/sanctions.csv", lines)


# List of SIAE member emails whose SIAE got a criteria refused
refused_lines = []
siae_with_refused_criteria_ids = set(
    models.EvaluatedAdministrativeCriteria.objects.filter(
        review_state__in=("REFUSED", "REFUSED_2"),
        evaluated_job_application__evaluated_siae__evaluation_campaign__evaluated_period_start_at="2022-01-01",
    ).values_list("evaluated_job_application__evaluated_siae__siae_id", flat=True)
)

for siae in Siae.objects.filter(pk__in=siae_with_refused_criteria_ids):
    for email in siae.active_members.values_list("email", flat=True):
        refused_lines.append(
            (
                siae.pk,
                siae.name,
                email,
            )
        )

export_lines_to_csv("/tmp/refused.csv", refused_lines)


# List of non-sanctioned SIAE member emails
lines = []

for sanction in models.Sanctions.objects.exclude(no_sanction_reason=""):
    evaluated = sanction.evaluated_siae
    for email in evaluated.siae.active_members.values_list("email", flat=True):
        lines.append(
            (
                evaluated.siae.pk,
                evaluated.siae.name,
                sanction.no_sanction_reason,
                email,
            )
        )

export_lines_to_csv("/tmp/no_sanctions.csv", lines)
