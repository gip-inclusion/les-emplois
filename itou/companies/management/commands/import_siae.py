"""

This script updates existing SIAEs and injects new ones
by joining the following two ASP datasets:
- Vue Structure (has most siae data except kind)
- Vue AF ("Annexes Financières", has kind and all financial annexes)

It should be played again after each upcoming Opening (HDF, the whole country...)
and each time we received a new export from the ASP.

Note that we use dataframes instead of csv reader mainly
because the main CSV has a large number of columns (30+)
and thus we need a proper tool to manage columns by their
name instead of hardcoding column numbers as in `field = row[42]`.

"""

from django.core.management.base import CommandError
from django.db import transaction

from itou.companies.management.commands._import_siae.convention import (
    check_convention_data_consistency,
    create_conventions,
    delete_conventions,
    update_existing_conventions,
)
from itou.companies.management.commands._import_siae.financial_annex import (
    manage_financial_annexes,
)
from itou.companies.management.commands._import_siae.siae import (
    check_whether_signup_is_possible_for_all_siaes,
    cleanup_siaes_after_grace_period,
    create_new_siaes,
    delete_user_created_siaes_without_members,
    manage_staff_created_siaes,
    update_siret_and_auth_email_of_existing_siaes,
)
from itou.companies.management.commands._import_siae.vue_af import (
    get_active_siae_keys,
    get_vue_af_df,
)
from itou.companies.management.commands._import_siae.vue_structure import (
    get_siret_to_siae_row,
    get_vue_structure_df,
)
from itou.utils.command import BaseCommand
from itou.utils.templatetags.str_filters import pluralizefr


class Command(BaseCommand):
    """
    Update and sync SIAE data based on latest ASP exports.

    Run the following command:
        django-admin import_siae
    """

    help = "Update and sync SIAE data based on latest ASP exports."

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @transaction.atomic
    def handle(self, wet_run, **options):
        errors = 0

        siret_to_siae_row = get_siret_to_siae_row(get_vue_structure_df())

        vue_af_df = get_vue_af_df()
        af_number_to_row = {row.number: row for _, row in vue_af_df.iterrows()}
        active_siae_keys = get_active_siae_keys(vue_af_df)

        # Sanitize data from users
        errors += delete_user_created_siaes_without_members()
        errors += manage_staff_created_siaes()

        errors += update_siret_and_auth_email_of_existing_siaes(siret_to_siae_row)
        update_existing_conventions(siret_to_siae_row, active_siae_keys)
        create_new_siaes(siret_to_siae_row, active_siae_keys)
        create_conventions(vue_af_df, siret_to_siae_row, active_siae_keys)
        delete_conventions()
        manage_financial_annexes(af_number_to_row)
        cleanup_siaes_after_grace_period()

        # Run some updates a second time.
        update_existing_conventions(siret_to_siae_row, active_siae_keys)
        errors += update_siret_and_auth_email_of_existing_siaes(siret_to_siae_row)
        delete_conventions()

        # Final checks.
        check_convention_data_consistency()
        errors += check_whether_signup_is_possible_for_all_siaes()

        if not wet_run:
            raise CommandError("DRY RUN mode, use --wet-run to apply changes")

        if errors >= 1:
            s = pluralizefr(errors)
            self.stdout.write(
                f"*** ERROR{s.upper()} *** The command completed all its actions successfully "
                f"but {errors} error{s} needs manual resolution, see the command's output"
            )
        else:
            self.stdout.write("All done!")
