from itou.approvals.enums import Origin
from itou.job_applications.models import JobApplication
from itou.metabase.db import DB_CURSOR, populate_table
from itou.metabase.tables.c1_analyses import JobApplicationsTable, UsersTable
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Populate c1 analyses database with data from itou database."

    def populate_users(self):
        queryset = (
            User.objects.filter(kind=UserKind.JOB_SEEKER)
            .select_related("created_by")
            .only(
                "pk",
                "kind",
                "date_joined",
                "first_login",
                "last_login",
                "created_by__kind",
                "created_by__is_staff",
            )
        )
        populate_table(UsersTable, batch_size=10_000, querysets=[queryset], cursor_name=DB_CURSOR.C1)

    def populate_job_applications(self):
        queryset = (
            JobApplication.objects.select_related("to_company", "sender_company", "sender_prescriber_organization")
            .only(
                "pk",
                "created_at",
                "processed_at",
                "state",
                "refusal_reason",
                "origin",
                "sender_kind",
                "sender_prescriber_organization__kind",
                "sender_prescriber_organization__is_authorized",
                "sender_company__kind",
                "job_seeker_id",
                "to_company__kind",
            )
            .exclude(origin=Origin.PE_APPROVAL)
            .all()
        )
        populate_table(JobApplicationsTable, batch_size=10_000, querysets=[queryset], cursor_name=DB_CURSOR.C1)

    def handle(self, **kwargs):
        self.populate_users()
        self.populate_job_applications()
