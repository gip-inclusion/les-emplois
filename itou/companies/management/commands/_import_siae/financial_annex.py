"""

SiaeFinancialAnnex object logic used by the import_siae.py script is gathered here.

"""

from django.utils import timezone

from itou.companies.models import SiaeConvention, SiaeFinancialAnnex


def get_creatable_and_deletable_afs(af_number_to_row):
    """
    Get AFs which should be created / deleted.

    Update existing AFs on the fly.

    Output : (creatable_afs, deletable_afs).
    """
    vue_af_numbers = set(af_number_to_row.keys())
    db_af_numbers = set()
    deletable_afs = []

    for af in SiaeFinancialAnnex.objects.select_related("convention"):
        db_af_numbers.add(af.number)

        if af.number not in vue_af_numbers:
            deletable_afs.append(af)
            continue

        # The AF already exists in db. Let's check if some of its fields have changed.
        row = af_number_to_row[af.number]
        assert af.number == row.number
        assert af.convention.kind == row.kind

        # Sometimes an AF start date changes.
        if af.start_at != timezone.make_aware(row.start_at):
            af.start_at = timezone.make_aware(row.start_at)
            af.save()

        # Sometimes an AF end date changes.
        if af.end_at != timezone.make_aware(row.end_at):
            af.end_at = timezone.make_aware(row.end_at)
            af.save()

        # Sometimes an AF state changes.
        if af.state != row.state:
            af.state = row.state
            af.save()

        # Sometimes an AF migrates from one convention to another.
        if af.convention.asp_id != row.asp_id:
            convention_query = SiaeConvention.objects.filter(asp_id=row.asp_id, kind=row.kind)
            if convention_query.exists():
                convention = convention_query.get()
                af.convention = convention
                af.save()
            else:
                deletable_afs.append(af)
                continue
        assert af.convention.asp_id == row.asp_id

    creatable_af_numbers = vue_af_numbers - db_af_numbers

    creatable_afs = [build_financial_annex_from_number(af_number_to_row, number) for number in creatable_af_numbers]

    # Drop None values (AFs without preexisting convention).
    creatable_afs = [af for af in creatable_afs if af]

    return (creatable_afs, deletable_afs)


def build_financial_annex_from_number(af_number_to_row, number):
    row = af_number_to_row[number]
    convention_query = SiaeConvention.objects.filter(asp_id=row.asp_id, kind=row.kind)
    if not convention_query.exists():
        # There is no point in storing an AF in db if there is no related convention.
        return None
    return SiaeFinancialAnnex(
        number=row.number,
        state=row.state,
        start_at=timezone.make_aware(row.start_at),
        end_at=timezone.make_aware(row.end_at),
        convention=convention_query.get(),
    )
