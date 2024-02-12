"""

SiaeFinancialAnnex object logic used by the import_siae.py script is gathered here.

"""

from django.utils import timezone

from itou.companies.models import SiaeConvention, SiaeFinancialAnnex


def get_creatable_and_deletable_afs(af_number_to_row):
    """
    Get AFs which should be created / deleted.

    Update existing AFs on the fly.

    Output: (creatable_afs, deletable_afs).
    """
    db_af_numbers = set()
    deletable_afs = []

    for af in SiaeFinancialAnnex.objects.select_related("convention"):
        db_af_numbers.add(af.number)

        if af.number not in af_number_to_row:
            deletable_afs.append(af)
            continue

        # The AF already exists in db. Let's check if some of its fields have changed.
        row = af_number_to_row[af.number]
        assert af.convention.kind == row.kind

        updated_fields = set()
        for field in ["start_at", "end_at"]:
            row_value = timezone.make_aware(getattr(row, field))
            if getattr(af, field) != row_value:
                setattr(af, field, row_value)
                updated_fields.add(field)

        # Sometimes an AF state changes.
        if af.state != row.state:
            af.state = row.state
            updated_fields.add("state")

        # Sometimes an AF migrates from one convention to another.
        if af.convention.asp_id != row.asp_id:
            try:
                convention = SiaeConvention.objects.get(asp_id=row.asp_id, kind=row.kind)
            except SiaeConvention.DoesNotExist:
                deletable_afs.append(af)
                continue
            else:
                af.convention = convention
                updated_fields.add("convention")

        af.save(update_fields=updated_fields)

    creatable_af_numbers = set(af_number_to_row) - db_af_numbers
    creatable_afs = list(
        filter(
            None,  # Drop None values (AFs without preexisting convention).
            [build_financial_annex_from_number(af_number_to_row[number]) for number in creatable_af_numbers],
        )
    )

    return creatable_afs, deletable_afs


def build_financial_annex_from_number(row):
    try:
        convention = SiaeConvention.objects.get(asp_id=row.asp_id, kind=row.kind)
    except SiaeConvention.DoesNotExist:
        # There is no point in storing an AF in db if there is no related convention.
        return None
    else:
        return SiaeFinancialAnnex(
            number=row.number,
            state=row.state,
            start_at=timezone.make_aware(row.start_at),
            end_at=timezone.make_aware(row.end_at),
            convention=convention,
        )


def manage_financial_annexes(af_number_to_row):
    creatable_afs, deletable_afs = get_creatable_and_deletable_afs(af_number_to_row)

    print(f"will create {len(creatable_afs)} financial annexes")
    for af in creatable_afs:
        af.save()

    print(f"will delete {len(deletable_afs)} financial annexes")
    for af in deletable_afs:
        af.delete()
