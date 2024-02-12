"""

SIAE object logic used by the import_siae.py script is gathered here.

All these helpers are specific to SIAE logic (not GEIQ, EA, EATT).

"""

from django.db.models import Q
from django.utils import timezone

from itou.common_apps.address.departments import department_from_postcode
from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.companies.management.commands._import_siae.utils import could_siae_be_deleted, geocode_siae
from itou.companies.models import Company, SiaeConvention
from itou.utils.emails import send_email_messages


def build_siae(row, kind, *, is_active):
    """
    Build a siae object from a dataframe row.

    Only for SIAE, not for GEIQ nor EA nor EATT.

    Using `is_active=True` will try to geocode the SIAE's address,
    if successful it will be visible in search results, hence active.
    """
    siae = Company()
    siae.siret = row.siret
    siae.kind = kind
    siae.naf = row.naf
    siae.source = Company.SOURCE_ASP
    siae.name = row["name"]  # row.name surprisingly returns the row index.
    assert not siae.name.isnumeric()

    siae.phone = row.phone
    phone_is_valid = siae.phone and len(siae.phone) == 10
    if not phone_is_valid:
        siae.phone = ""  # siae.phone cannot be null in db

    siae.email = ""  # Do not make the authentification email public!
    siae.auth_email = row.auth_email

    street_num = row.street_num
    if street_num:
        street_num = int(street_num)
    street_num = f"{street_num or ''} {row.street_num_extra or ''}"
    street_name = f"{row.street_type or ''} {row.street_name or ''}"
    address_line_1 = f"{street_num} {street_name}"
    # Replace multiple spaces by a single space.
    address_line_1 = " ".join(address_line_1.split())
    siae.address_line_1 = address_line_1.strip()

    address_line_2 = f"{row.extra1 or ''} {row.extra2 or ''} {row.extra3 or ''}"
    # Replace multiple spaces by a single space.
    address_line_2 = " ".join(address_line_2.split())
    siae.address_line_2 = address_line_2.strip()

    # Avoid confusing case where line1 is empty and line2 is not.
    if not siae.address_line_1:
        siae.address_line_1 = siae.address_line_2
        siae.address_line_2 = ""

    siae.city = row.city
    siae.post_code = row.post_code
    siae.department = department_from_postcode(siae.post_code)

    if is_active:
        geocode_siae(siae)
    return siae


def update_siret_and_auth_email_of_existing_siaes(siret_to_siae_row):
    auth_email_updates, errors = 0, 0

    asp_id_to_siae_row = {row.asp_id: row for row in siret_to_siae_row.values()}
    for siae in Company.objects.select_related("convention").filter(
        source=Company.SOURCE_ASP, convention__isnull=False
    ):
        assert siae.should_have_convention

        if siae.convention.asp_id not in asp_id_to_siae_row:
            continue
        row = asp_id_to_siae_row[siae.convention.asp_id]
        updated_fields = set()

        auth_email = row.auth_email or siae.auth_email
        if siae.auth_email != auth_email:
            siae.auth_email = auth_email
            updated_fields.add("auth_email")
            auth_email_updates += 1

        if siae.siret != row.siret:
            assert siae.siren == row.siret[:9]

            existing_siae = Company.objects.filter(siret=row.siret, kind=siae.kind).first()
            if existing_siae:

                def fmt(siae):
                    msg = f"{siae.source} {siae.siret}"
                    if siae.convention is None:
                        return f"{msg} convention=None"
                    return f"{msg} convention.id={siae.convention.id} asp_id={siae.convention.asp_id}"

                print(
                    f"ERROR: siae.id={siae.id} ({fmt(siae)}) has changed siret from "
                    f"{siae.siret} to {row.siret} but new siret is already used by "
                    f"siae.id={existing_siae.id} ({fmt(existing_siae)}) "
                )
                errors += 1
                continue

            print(f"siae.id={siae.id} has changed siret from {siae.siret} to {row.siret} (will be updated)")
            siae.siret = row.siret
            updated_fields.add("siret")

        if updated_fields:
            siae.save(update_fields=updated_fields)

    print(f"{auth_email_updates} siae.auth_email fields have been updated")
    return errors


def create_new_siaes(siret_to_siae_row, active_siae_keys):
    creatable_siaes = []

    asp_id_to_siae_row = {row.asp_id: row for row in siret_to_siae_row.values()}
    for asp_id, kind in active_siae_keys:
        if asp_id not in asp_id_to_siae_row:
            continue
        row = asp_id_to_siae_row[asp_id]

        existing_siaes = Company.objects.select_related("convention").filter(convention__asp_id=asp_id, kind=kind)
        if existing_siaes:
            # Siaes with this asp_id already exist, no need to create one more.
            total_existing_siaes_with_asp_source = 0
            for existing_siae in existing_siaes:
                assert existing_siae.should_have_convention
                if existing_siae.source == Company.SOURCE_ASP:
                    total_existing_siaes_with_asp_source += 1
                    # Siret should have been fixed by update_siret_and_auth_email_of_existing_siaes().
                    assert existing_siae.siret == row.siret
                else:
                    assert existing_siae.source == Company.SOURCE_USER_CREATED

            # Duplicate siaes should have been deleted.
            assert total_existing_siaes_with_asp_source == 1
            continue

        try:
            existing_siae = Company.objects.get(~Q(source=Company.SOURCE_ASP), siret=row.siret, kind=kind)
        except Company.DoesNotExist:
            assert not SiaeConvention.objects.filter(asp_id=asp_id, kind=kind).exists()
            if (row.asp_id, kind) in active_siae_keys:
                creatable_siaes.append(build_siae(row, kind, is_active=True))
        else:
            # Siae with this siret+kind already exists but with the wrong source.
            assert existing_siae.source in [Company.SOURCE_USER_CREATED, Company.SOURCE_STAFF_CREATED]
            assert existing_siae.should_have_convention
            print(
                f"siae.id={existing_siae.id} already exists "
                f"with wrong source={existing_siae.source} "
                f"(source will be fixed to ASP)"
            )
            existing_siae.source = Company.SOURCE_ASP
            existing_siae.convention = None
            existing_siae.save(update_fields={"source", "convention"})

    print("--- beginning of CSV output of all creatable_siaes ---")
    print("siret;kind;department;name;address")
    for siae in creatable_siaes:
        print(f"{siae.siret};{siae.kind};{siae.department};{siae.name};{siae.address_on_one_line}")
        siae.save()
    print("--- end of CSV output of all creatable_siaes ---")

    send_email_messages(siae.activate_your_account_email() for siae in creatable_siaes)

    print(f"{len(creatable_siaes)} structures have been created")
    print(f"{len([s for s in creatable_siaes if s.coords])} structures will have geolocation")


def cleanup_siaes_after_grace_period():
    deletions, blocked_deletions = 0, 0

    for siae in Company.objects.select_related("convention"):
        if not siae.grace_period_has_expired:
            continue

        if could_siae_be_deleted(siae):
            siae.delete()
            deletions += 1
        else:
            blocked_deletions += 1

    print(f"{deletions} siaes past their grace period has been deleted")
    print(f"{blocked_deletions} siaes past their grace period cannot be deleted")


def delete_user_created_siaes_without_members():
    """
    Siaes created by a user usually have at least one member, their creator.
    However in some cases, itou staff deletes some users, leaving
    potentially user created siaes without member.
    Those siaes cannot be joined by any way and thus are useless.
    Let's clean them up when possible.
    """
    errors = 0
    for siae in Company.objects.prefetch_related("memberships").filter(
        members__isnull=True, source=Company.SOURCE_USER_CREATED
    ):
        if not siae.has_members:
            if could_siae_be_deleted(siae):
                print(f"siae.id={siae.id} is user created and has no member thus will be deleted")
                siae.delete()
            else:
                print(
                    f"ERROR: siae.id={siae.id} is user created and "
                    f"has no member but has job applications thus cannot be deleted"
                )
                errors += 1

    return errors


def manage_staff_created_siaes():
    """
    Itou staff regularly creates siaes manually when ASP data lags behind for some specific employers.

    Normally the SIRET later appears in ASP data then the siae is converted to ASP source by `create_new_siaes`.

    But sometimes a staff created siae's SIRET never appear in ASP data. We wait 90 days (as decided with staff
    team) before considering it invalid and attempting deleting it.

    If the siae cannot be deleted because it has data, a warning will be shown to supportix.
    """
    three_months_ago = timezone.now() - timezone.timedelta(days=90)
    staff_created_siaes = Company.objects.filter(
        kind__in=SIAE_WITH_CONVENTION_KINDS,
        source=Company.SOURCE_STAFF_CREATED,
    )
    # Sometimes our staff creates a siae then later attaches it manually to the correct convention. In that
    # case it should be converted to a regular user created siae so that the usual convention logic applies.
    for siae in staff_created_siaes.filter(convention__isnull=False):
        print(f"converted staff created siae.id={siae.id} to user created siae as it has a convention")
        siae.source = Company.SOURCE_USER_CREATED
        siae.save(update_fields={"source"})

    recent_unconfirmed_siaes = staff_created_siaes.filter(created_at__gte=three_months_ago)
    print(
        f"{recent_unconfirmed_siaes.count()} siaes created recently by staff"
        " (still waiting for ASP data to be confirmed)"
    )

    old_unconfirmed_siaes = staff_created_siaes.filter(created_at__lt=three_months_ago)
    print(f"{len(old_unconfirmed_siaes)} siaes created by staff should be deleted as they are unconfirmed")
    errors = 0
    for siae in old_unconfirmed_siaes:
        if could_siae_be_deleted(siae):
            print(f"deleted unconfirmed siae.id={siae.id} created by staff a while ago")
            siae.delete()
        else:
            print(
                f"ERROR: Please fix unconfirmed staff created siae.id={siae.id}"
                f" by either deleting it or attaching it to the correct convention"
            )
            errors += 1

    return errors


def check_whether_signup_is_possible_for_all_siaes():
    errors = 0

    no_signup_siaes = Company.objects.filter(auth_email="").exclude(companymembership__is_active=True).distinct()
    for siae in no_signup_siaes:
        print(
            f"ERROR: signup is impossible for siae.id={siae.id} siret={siae.siret} "
            f"kind={siae.kind} dpt={siae.department} source={siae.source} "
            f"created_by={siae.created_by} siae.email={siae.email}"
        )
        errors += 1

    return errors
