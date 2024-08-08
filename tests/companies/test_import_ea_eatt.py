import datetime
import io
import re
import zipfile

import pytest

from itou.companies.management.commands import import_ea_eatt
from itou.companies.models import Company
from itou.utils.asp import REMOTE_DOWNLOAD_DIR, REMOTE_UPLOAD_DIR
from itou.utils.date import monday_of_the_week


@pytest.fixture(name="command")
def command_fixture(mocker, settings, sftp_directory, sftp_client_factory):
    # Set required settings
    settings.ASP_SFTP_HOST = "0.0.0.0"  # non-routable IP, just in case :)
    settings.ASP_SFTP_USER = "django_tests"

    # Setup directory
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).mkdir()
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).mkdir()

    # Create the management command and mock the SFTP connection
    command = import_ea_eatt.Command(stdout=io.StringIO(), stderr=io.StringIO())
    mocker.patch("itou.utils.asp.get_sftp_connection", sftp_client_factory)

    return command


@pytest.fixture(name="archive_file")
def archive_file_fixture():
    archive = io.BytesIO()

    data = [
        "L|ASP|EA|V1.0|20241231|235959|",  # File header
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
        # File footer
        "Z|ASP|EA|20241231|235959|4|7|",
    ]
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as fp:
        fp.setpassword(b"password")
        fp.writestr("EA2_ITOU.txt", data="\n".join(data))

    archive.seek(0)
    return archive


def test_retrieve_archive_of_the_week(faker, sftp_directory, command):
    monday = monday_of_the_week()
    monday_archive = sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(monday))
    monday_archive.write_bytes(faker.zip())
    assert command.retrieve_archive_of_the_week().getvalue()


def test_retrieve_archive_of_the_week_errors(faker, sftp_directory, command):
    monday = monday_of_the_week()

    with pytest.raises(RuntimeError, match="No file for this week: "):
        command.retrieve_archive_of_the_week()

    sunday_before_monday = monday - datetime.timedelta(days=1)
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(sunday_before_monday)).touch()
    with pytest.raises(RuntimeError, match="No file for this week: "):
        command.retrieve_archive_of_the_week()

    monday_archive = sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(monday))
    monday_archive.write_bytes(faker.zip())
    assert command.retrieve_archive_of_the_week().getvalue()

    tuesday_after_monday = monday + datetime.timedelta(days=1)
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(tuesday_after_monday)).touch()
    with pytest.raises(RuntimeError, match="Too many files for this week: "):
        command.retrieve_archive_of_the_week()


def test_clean_old_archives(faker, mocker, sftp_directory, command):
    expected_files = set()
    for day in range(3):
        filename = faker.asp_ea2_filename(datetime.date(2024, 8, 1 + day))
        sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, filename).touch()
        expected_files.add(filename)

    assert {file.name for file in sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir()} == expected_files
    command.clean_old_archives(wet_run=True)
    assert {file.name for file in sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir()} == expected_files

    mocker.patch.object(command, "NUMBER_OF_ARCHIVES_TO_KEEP", 1)
    command.clean_old_archives(wet_run=True)
    assert {file.name for file in sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir()} == {
        faker.asp_ea2_filename(datetime.date(2024, 8, 3))
    }


def test_clean_old_archives_dry_run(faker, mocker, sftp_directory, command):
    mocker.patch.object(command, "NUMBER_OF_ARCHIVES_TO_KEEP", 0)
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, faker.asp_ea2_filename(monday_of_the_week())).touch()

    assert len(set(sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir())) == 1
    command.clean_old_archives(wet_run=False)
    assert len(set(sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir())) == 1


def test_process_file_from_archive(capsys, snapshot, settings, command, archive_file):
    settings.ASP_EA2_UNZIP_PASSWORD = "password"

    command.handle(from_archive=archive_file, wet_run=True)
    assert re.sub(r"siae.id=\d+", "siae.id=[ID]", capsys.readouterr()[0] + command.stdout.getvalue()) == snapshot(
        name="output"
    )
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
