import pgtrigger
from django.db.models import F
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.approvals.models import Prolongation, Suspension
from itou.utils.admin import add_support_remark_to_obj
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def fix_prolongations_ending_after(self):
        for prolongation in Prolongation.objects.filter(end_at__gt=F("approval__end_at")):
            approval = prolongation.approval
            old_end_at = approval.end_at
            approval.end_at = prolongation.end_at
            approval.save(update_fields=["end_at", "updated_at"])
            log_string = (
                "allongement d'un PASS finissant avant la dernière prologation"
                f" pass_iae={approval.number} old_end_at={old_end_at}"
                f" new_end_at={approval.end_at}"
            )
            add_support_remark_to_obj(
                approval,
                f"------------------------\n{timezone.localtime().replace(microsecond=0)} (automatique): {log_string}",
            )
            self.stdout.write(log_string)

    def fix_suspensions_starting_after(self):
        for suspension in Suspension.objects.filter(start_at__gt=F("approval__end_at")):
            approval = suspension.approval
            s_data = {k: str(v) for k, v in suspension.__dict__.items() if k != "_state"}
            with pgtrigger.ignore("approvals.Suspension:update_approval_end_at"):
                suspension.delete()
            log_string = (
                "suppression d'une suspension commençant après la fin du PASS"
                f" (sans modifier la date de fin du PASS): {s_data}"
            )
            add_support_remark_to_obj(
                approval,
                f"------------------------\n{timezone.localtime().replace(microsecond=0)} (automatique): {log_string}",
            )
            self.stdout.write(log_string)

    def fix_suspensions_ending_after(self):
        for suspension in Suspension.objects.filter(end_at__gt=F("approval__end_at")):
            approval = suspension.approval
            old_end_at = suspension.end_at
            with pgtrigger.ignore("approvals.Suspension:update_approval_end_at"):
                suspension.end_at = approval.end_at
                suspension.updated_by = None
                suspension.save(update_fields=["end_at", "updated_at", "updated_by"])
            log_string = (
                "raccourcissement d'une suspension finissant après la fin du PASS"
                f" (sans modifier la date de fin du PASS): suspension={suspension.pk} old_end_at={old_end_at}"
                f" new_end_at={suspension.end_at}"
            )
            add_support_remark_to_obj(
                approval,
                f"------------------------\n{timezone.localtime().replace(microsecond=0)} (automatique): {log_string}",
            )
            self.stdout.write(log_string)

    @dry_runnable
    def handle(self, *args, **options):
        self.fix_prolongations_ending_after()
        self.fix_suspensions_starting_after()
        self.fix_suspensions_ending_after()
