"""

SiaeFinancialAnnex object logic used by the import_siae.py script is gathered here.

"""
from itou.siaes.management.commands._import_siae.vue_af import AF_NUMBER_TO_ROW
from itou.siaes.models import SiaeConvention, SiaeFinancialAnnex


def get_creatable_and_deletable_afs(dry_run):
    """
    Get AFs which should be created / deleted.

    Update existing AFs on the fly.

    Output : (creatable_afs, deletable_afs).
    """
    vue_af_numbers = set(AF_NUMBER_TO_ROW.keys())
    db_af_numbers = set()
    deletable_afs = []

    for af in SiaeFinancialAnnex.objects.select_related("convention"):
        db_af_numbers.add(af.number)

        if af.number not in vue_af_numbers:
            deletable_afs.append(af)
            continue

        # The AF already exists in db. Let's check if some of its fields have changed.
        row = AF_NUMBER_TO_ROW[af.number]
        assert af.number == row.number
        assert af.convention_number == row.convention_number
        assert af.start_at == row.start_date
        assert af.end_at == row.end_date
        assert af.convention.kind == row.kind

        # Sometimes an AF state changes.
        if af.state != row.state:
            af.state = row.state
            if not dry_run:
                af.save()

        # Sometimes an AF migrates from one structure to another.
        if af.convention.asp_id != row.external_id:
            convention_query = SiaeConvention.objects.filter(asp_id=row.external_id)
            if convention_query.exists():
                convention = convention_query.get()
                af.convention = convention
                if not dry_run:
                    af.save()
            else:
                deletable_afs.append(af)
                continue
        assert af.convention.asp_id == row.external_id

    creatable_af_numbers = vue_af_numbers - db_af_numbers

    creatable_afs = [build_financial_annex_from_number(number) for number in creatable_af_numbers]

    # Drop None values (AFs without preexisting convention).
    creatable_afs = [af for af in creatable_afs if af]

    return (creatable_afs, deletable_afs)


def build_financial_annex_from_number(number):
    row = AF_NUMBER_TO_ROW[number]
    convention_query = SiaeConvention.objects.filter(asp_id=row.external_id, kind=row.kind)
    if not convention_query.exists():
        # There is no point in storing an AF in db if there is no related convention.
        return None
    return SiaeFinancialAnnex(
        number=row.number,
        convention_number=row.convention_number,
        state=row.state,
        start_at=row.start_date,
        end_at=row.end_date,
        convention=convention_query.get(),
    )
