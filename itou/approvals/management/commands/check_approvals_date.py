from django.db.models import Q

from itou.approvals.models import Approval, OriginalPoleEmploiApproval, PoleEmploiApproval
from itou.utils.command import BaseCommand


INDENT = " " * 2


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--fix", dest="fix", action="store_true", help="Fix approvals date mismatch")
        parser.add_argument("--wet-run", dest="wet_run", action="store_true", help="Allow to alter the data")

    def handle(self, *, fix, wet_run, **options):
        converted_approvals = Approval.objects.filter(~Q(number__startswith=Approval.ASP_ITOU_PREFIX))

        for approval in converted_approvals.order_by("number").select_related("created_by"):
            errors = []
            fixable_fields = set()

            try:
                pe_approval = PoleEmploiApproval.objects.only("start_at", "end_at").get(number=approval.number)
            except PoleEmploiApproval.DoesNotExist:
                self.stdout.write(f"Approval {approval.number} doesn't exists as PoleEmploiApproval.")
                continue

            original_pe_approvals = (
                OriginalPoleEmploiApproval.objects.filter(number__startswith=approval.number)
                .order_by("created_at")
                .only("start_at", "end_at")
            )

            if approval.start_at != pe_approval.start_at:
                errors.append(
                    f"- Doesn't have the same start date: "
                    f"Approval.start_at={approval.start_at}, PoleEmploiApproval.start_at={pe_approval.start_at}"
                )
                for original_pe_approval in original_pe_approvals:
                    if approval.start_at == original_pe_approval.start_at:
                        errors.append(
                            INDENT + f"> The OriginalPoleEmploiApproval.start_at used was {original_pe_approval}"
                        )
                        fixable_fields.add("start_at")
            if approval.end_at < pe_approval.end_at:
                errors.append(
                    f"- End before the PoleEmploiApproval: "
                    f"Approval.end_at={approval.end_at}, PoleEmploiApproval.end_at={pe_approval.end_at}"
                )
                for original_pe_approval in original_pe_approvals:
                    if approval.end_at == original_pe_approval.end_at:
                        errors.append(
                            INDENT + f"> The OriginalPoleEmploiApproval.end_at used was {original_pe_approval}"
                        )
                        fixable_fields.add("end_at")

            if errors:
                self.stdout.write(
                    f"Approval {approval.number} (at={approval.created_at.date()}, by={approval.created_by}):"
                )
                for error in errors:
                    self.stdout.write(INDENT + error)

            if fix and fixable_fields:
                diff = {}
                for field in fixable_fields:
                    diff[field] = {"old": getattr(approval, field), "new": getattr(pe_approval, field)}
                    setattr(approval, field, getattr(pe_approval, field))

                self.stdout.write(INDENT + f"# Fixing: {diff}")
                if wet_run:
                    self.stdout.write(INDENT * 2 + "> Done!")
                    approval.save(update_fields=fixable_fields)
