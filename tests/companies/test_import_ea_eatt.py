import contextlib
import datetime
import random
import zipfile

import pytest
from django.core.management import call_command
from freezegun import freeze_time

from itou.companies.enums import CompanyKind
from itou.companies.management.commands import import_ea_eatt
from itou.companies.management.commands.import_ea_eatt import FileOfTheWeekNotFound
from itou.companies.models import Company
from itou.utils.asp import REMOTE_DOWNLOAD_DIR, REMOTE_UPLOAD_DIR
from itou.utils.date import monday_of_the_week
from tests.companies.factories import CompanyFactory


@pytest.fixture(name="mocked_sftp")
def mocked_sftp_fixture(mocker, settings, sftp_directory, sftp_client_factory):
    # Set required settings
    settings.ASP_SFTP_HOST = "0.0.0.0"  # non-routable IP, just in case :)
    settings.ASP_SFTP_USER = "django_tests"

    # Setup directory
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).mkdir()
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).mkdir()

    # mock the SFTP connection
    mocker.patch("itou.utils.asp.get_sftp_connection", sftp_client_factory)


@pytest.fixture(name="archive_file_name")
def archive_file_name_fixture(tmp_path):
    file_name = tmp_path / "archive.zip"

    data = [
        # File header
        "L|ASP|EA|V1.0|20241231|235959|",
        # Columns headers
        "ITOU|Type d'entreprise adaptée|Numéro de COT/CPOM|Identifiant EA2 Signataire|Siret Signataire"
        "|Dénomination / raison sociale Signataire|Courriel du contact étab signataire|Siret de l'établissement membre"
        "|Dénomination / raison sociale|Identifiant EA2 Etablissement|Numéro entrée ou batiment|Numéro de voie"
        "|Extension de voie|Code voie|Libelle de la voie|Code Postal|Code INSEE commune|",
        # EA in same COT/CPOM than an EATT
        "ITOU|Entreprise Adaptée|00000001|1|00000000000001|Dumas SA|legerdenise@example.org"
        "|00000000000001|Dumas SA|1||1||Rue|DE LA MOTTE|77550|77296|",
        # EATT in same COT/CPOM than an EA
        "ITOU|Entreprise Adaptée Travail Temporaire|00000001|1|00000000000001|Dumas SA|legerdenise@example.org"
        "|00000000000001|Collet SARL|2||1||Rue|DE LA MOTTE|77550|77296|",
        # EAMP - Should be ignored
        "ITOU|Entreprise Adaptée en Milieu Pénitentiaire |00000001|1|00000000000001|Dumas SA|legerdenise@example.org"
        "|00000000000001|Lemaître S.A.S.|3||1||Rue|DE LA MOTTE|77550|77296|",
        # EA duplicate (by SIRET) - Should be ignored
        "ITOU|Entreprise Adaptée|00000001|4|00000000000001|Dumas SA|legerdenise@example.org"
        "|00000000000001|Dumas SA|4||1||Rue|DE LA MOTTE|77550|77296|",
        # EA with missing email
        "ITOU|Entreprise Adaptée|00000001|5|00000000000002|Nomail SA|"
        "|00000000000002|Nomail SA|5||1||Rue|DE LA MOTTE|77550|77296|",
        # EA already present in database
        "ITOU|Entreprise Adaptée|00000001|6|00000000000003|Nomail SA|"
        "|00000000000003|Adapted SA|6||1||Rue|DE LA MEUTE|77550|77296|",
        # File footer
        "Z|ASP|EA|20241231|235959|4|7|",
    ]
    with open(file_name, "wb") as archive, zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as fp:
        fp.setpassword(b"password")
        fp.writestr("EA2_ITOU.txt", data="\n".join(data))

    return file_name


@pytest.fixture(name="archive_file_name_without_companies")
def archive_file_name_without_companies_fixture(tmp_path):
    file_name = tmp_path / "archive.zip"
    data = [
        # File header
        "L|ASP|EA|V1.0|20260105|092352|",
        # Columns headers
        "ITOU|Type d'entreprise adaptée|Numéro de COT/CPOM|Identifiant EA2 Signataire|Siret Signataire"
        "|Dénomination / raison sociale Signataire|Courriel du contact étab signataire|Siret de l'établissement membre"
        "|Dénomination / raison sociale|Identifiant EA2 Etablissement|Numéro entrée ou batiment|Numéro de voie"
        "|Extension de voie|Code voie|Libelle de la voie|Code Postal|Code INSEE commune|",
        # File footer
        "Z|ASP|EA|20260105|092352|0|3|",
    ]
    with open(file_name, "wb") as archive, zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as fp:
        fp.setpassword(b"password")
        fp.writestr("EA2_ITOU.txt", data="\n".join(data))

    return file_name


def extract_logs(caplog, *, extra_keys=None, with_command_result=None):
    keys = ["module", "funcName", "levelno", "message"] + (extra_keys or [])
    if with_command_result:
        assert caplog.records[-1].message.startswith(
            f"Management command itou.companies.management.commands.import_ea_eatt {with_command_result} in"
        )
        log_records = caplog.records[:-1]
    else:
        log_records = caplog.records
    return [{key: getattr(record, key) for key in keys if hasattr(record, key)} for record in log_records]


@freeze_time("2025-05-12")
@pytest.mark.usefixtures("mocked_sftp")
def test_retrieve_archive_of_the_week(caplog, snapshot, faker, sftp_directory):
    monday = monday_of_the_week()
    monday_archive = sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(monday))
    monday_archive.write_bytes(faker.zip())
    # Others files shouldn't create problems
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_batch_filename()).touch()

    assert import_ea_eatt.Command().retrieve_archive_of_the_week().getvalue()
    assert extract_logs(caplog) == snapshot(name="logs")


@pytest.mark.parametrize(
    "date",
    [
        (datetime.date(2025, 4, 21)),
        (datetime.date(2025, 6, 9)),
        (datetime.date(2025, 7, 14)),
    ],
    ids=str,
)
@pytest.mark.usefixtures("mocked_sftp")
def test_retrieve_archive_of_the_week_when_monday_is_a_holiday(faker, sftp_directory, date):
    day_after_holiday = date + datetime.timedelta(days=random.randint(1, 6))
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(day_after_holiday)).write_bytes(faker.zip())

    with freeze_time(day_after_holiday):
        assert import_ea_eatt.Command().retrieve_archive_of_the_week().getvalue()


@pytest.mark.usefixtures("mocked_sftp")
def test_retrieve_archive_of_the_week_errors(faker, sftp_directory):
    monday = monday_of_the_week()

    with pytest.raises(FileOfTheWeekNotFound):
        import_ea_eatt.Command().retrieve_archive_of_the_week()

    sunday_before_monday = monday - datetime.timedelta(days=1)
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(sunday_before_monday)).touch()
    with pytest.raises(FileOfTheWeekNotFound):
        import_ea_eatt.Command().retrieve_archive_of_the_week()

    monday_archive = sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(monday))
    monday_archive.write_bytes(faker.zip())
    assert import_ea_eatt.Command().retrieve_archive_of_the_week().getvalue()

    tuesday_after_monday = monday + datetime.timedelta(days=1)
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(tuesday_after_monday)).touch()
    with pytest.raises(RuntimeError, match="Too many files for this week: "):
        import_ea_eatt.Command().retrieve_archive_of_the_week()


@pytest.mark.usefixtures("mocked_sftp")
def test_clean_old_archives(caplog, snapshot, faker, mocker, sftp_directory):
    expected_files = set()
    for day in range(3):
        filename = faker.asp_ea2_filename(datetime.date(2024, 8, 1 + day))
        sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, filename).touch()
        expected_files.add(filename)

    assert {file.name for file in sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir()} == expected_files
    import_ea_eatt.Command().clean_old_archives(wet_run=True)
    assert {file.name for file in sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir()} == expected_files

    mocker.patch.object(import_ea_eatt.Command, "NUMBER_OF_ARCHIVES_TO_KEEP", 1)
    import_ea_eatt.Command().clean_old_archives(wet_run=True)
    assert {file.name for file in sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir()} == {
        faker.asp_ea2_filename(datetime.date(2024, 8, 3))
    }
    assert extract_logs(caplog) == snapshot(name="logs")


@freeze_time("2025-05-12")
@pytest.mark.usefixtures("mocked_sftp")
def test_clean_old_archives_dry_run(caplog, snapshot, faker, mocker, sftp_directory):
    mocker.patch.object(import_ea_eatt.Command, "NUMBER_OF_ARCHIVES_TO_KEEP", 0)
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(monday_of_the_week())).touch()

    assert len(set(sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir())) == 1
    import_ea_eatt.Command().clean_old_archives(wet_run=False)
    assert len(set(sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir())) == 1
    assert extract_logs(caplog) == snapshot(name="logs")


@pytest.mark.usefixtures("mocked_sftp")
def test_process_file_from_archive(caplog, snapshot, settings, archive_file_name):
    settings.ASP_EA2_UNZIP_PASSWORD = "password"

    CompanyFactory(kind=CompanyKind.EA, siret="00000000000003")

    call_command("import_ea_eatt", from_archive_name=archive_file_name, wet_run=True)

    assert extract_logs(caplog, extra_keys=["info_stats"], with_command_result="succeeded") == snapshot(name="logs")

    filled_fields = [
        "kind",
        "siret",
        "source",
        "name",
        "email",
        "auth_email",
        "address_line_1",
        "address_line_2",
        "post_code",
        "insee_city",
        "city",
        "department",
        "coords",
    ]
    assert list(Company.objects.all().order_by("pk").values_list(*filled_fields)) == snapshot(name="data")


@pytest.mark.usefixtures("mocked_sftp")
def test_process_file_when_there_is_no_company_rows(caplog, snapshot, settings, archive_file_name_without_companies):
    settings.ASP_EA2_UNZIP_PASSWORD = "password"

    call_command("import_ea_eatt", from_archive_name=archive_file_name_without_companies, wet_run=True)

    assert extract_logs(caplog, extra_keys=["info_stats"], with_command_result="succeeded") == snapshot(name="logs")
    assert Company.objects.all().count() == 0


@pytest.mark.parametrize(
    "day_of_the_week,expectation,command_result",
    [
        pytest.param(0, contextlib.nullcontext(), "succeeded", id="monday"),
        pytest.param(1, contextlib.nullcontext(), "succeeded", id="tuesday"),
        pytest.param(2, contextlib.nullcontext(), "succeeded", id="wednesday"),
        pytest.param(3, contextlib.nullcontext(), "succeeded", id="thursday"),
        pytest.param(4, pytest.raises(RuntimeError, match="No file for this week"), "failed", id="friday"),
    ],
)
@pytest.mark.usefixtures("mocked_sftp")
def test_command_errors(caplog, snapshot, day_of_the_week, expectation, command_result):
    with expectation:
        with freeze_time(datetime.date(2025, 7, 14) + datetime.timedelta(days=day_of_the_week)):
            call_command("import_ea_eatt", from_asp=True)
    assert extract_logs(caplog, with_command_result=command_result) == snapshot(name="logs")
