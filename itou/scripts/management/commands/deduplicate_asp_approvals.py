import argparse

from itou.approvals.models import Approval
from itou.users.models import User
from itou.utils.command import BaseCommand


CSV_SEPARATOR = ";"


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "-d", "--debug", help="Add debug output alongside CSV output", action=argparse.BooleanOptionalAction
        )
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Path of the ASP CSV file to deduplicate",
        )

    def handle(self, file_path, *, debug, **options):
        def debug_log(s):
            if debug:
                self.stdout.write(f"[DEBUG_LOG] {s}")

        with open(file_path, encoding="utf-8") as input_file:
            input_file.readline()
            for line in input_file:
                [id_itou, number, _, _, _, name, first_name, birthday] = line.split(CSV_SEPARATOR)[:8]
                approval = Approval.objects.select_related("user").get(number=number)
                user = approval.user
                if id_itou == user.asp_uid:
                    debug_log(f"> HASH ID MATCH for pass={number} user={user}")
                    self.stdout.write(line)
                else:
                    debug_log(
                        f"! NO HASH ID MATCH for pass_number={number} pass_user={user}, "
                        f"linked in ASP to {first_name} {name}"
                    )
                    users = User.objects.filter(last_name__icontains=name, first_name__icontains=first_name)
                    for user in users:
                        if user.birthdate and birthday == f"{user.birthdate:%d/%m/%Y}":
                            debug_log(f"\t> FOUND BY NAME {user.first_name} {user.last_name}")
                            possible_passes = Approval.objects.filter(user=user)
                            debug_log(f"\t\t> FOUND count={possible_passes.count()} passes")
                            for pass_iae in possible_passes:
                                debug_log(f"\t\t> EXAMINING PASS expected={number} actual={pass_iae.number}")
                                if pass_iae.number == number:
                                    debug_log("\t\t> MATCHING APPROVAL FOUND")
                                    break
                                else:
                                    debug_log(
                                        f"\t\t! NO MATCH: ASP thinks pass_number={number} belongs to user={user} "
                                        f"but it belongs to pass_user={approval.user}"
                                    )
                                    break
                            else:
                                debug_log(
                                    f"\t\t! NO MATCH: ASP thinks pass_number={number} belongs to user={user} "
                                    f"but that person has no PASS, or it has been deleted."
                                )
                                break
                            break
                    else:
                        debug_log(f"\t! NO USER FOUND FOR {first_name} {name}")
