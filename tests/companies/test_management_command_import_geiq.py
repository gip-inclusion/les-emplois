import pytest
from faker import Faker

from itou.companies.management.commands.import_geiq import get_geiq_df
from itou.utils.export import generate_excel_sheet
from tests.utils.test import create_fake_postcode


faker = Faker()

FILE_HEADERS = ["Nom", "Rue", "Rue (suite)", "Code Postal", "Ville", "SIRET", "e-mail"]


def generate_data(rows=185, rows_with_empty_siret=0, rows_with_empty_email=0, duplicated_sirets=0):
    data = []
    rows_count = 0
    duplicated_sirets_count = 0
    while rows_count < rows:
        if rows_with_empty_siret > 0:
            siret = ""
            rows_with_empty_siret -= 1
        else:
            siret = faker.numerify("1#############")

        if rows_with_empty_email > 0:
            email = ""
            rows_with_empty_email -= 1
        else:
            email = faker.email()

        row = [
            faker.name(),
            faker.street_address(),
            "Sous l'escalier",
            create_fake_postcode(),
            faker.city(),
            siret,
            email,
        ]

        data.append(row)

        if duplicated_sirets_count < duplicated_sirets:
            data.append(row)
            rows_count += 1
            duplicated_sirets_count += 1

        rows_count += 1
    return data


def test_get_geiq_df(sftp_directory, faker):
    # Correct data
    rows = 185
    rows_with_empty_siret = 0
    rows_with_empty_email = 0
    data = generate_data(
        rows=rows, rows_with_empty_siret=rows_with_empty_siret, rows_with_empty_email=rows_with_empty_email
    )
    file_path = sftp_directory.joinpath(faker.geiq_filename())
    with open(file_path, "wb") as xlsxfile:
        workbook = generate_excel_sheet(FILE_HEADERS, data)
        workbook.save(xlsxfile)
    df, info_stats = get_geiq_df(file_path)
    assert df.shape == (rows, 8)
    assert info_stats == {
        "rows_in_file": rows,
        "rows_with_a_siret": rows,
        "rows_after_deduplication": rows,
        "rows_with_empty_email": rows_with_empty_email,
    }

    # File too small, need at least 150 rows
    rows = 140
    rows_with_empty_siret = 0
    rows_with_empty_email = 0
    data = generate_data(
        rows=rows, rows_with_empty_siret=rows_with_empty_siret, rows_with_empty_email=rows_with_empty_email
    )
    file_path = sftp_directory.joinpath(faker.geiq_filename())
    with open(file_path, "wb") as xlsxfile:
        workbook = generate_excel_sheet(FILE_HEADERS, data)
        workbook.save(xlsxfile)
    with pytest.raises(AssertionError):
        df, info_stats = get_geiq_df(file_path)

    # Too many missing emails
    rows = 185
    rows_with_empty_siret = 0
    rows_with_empty_email = 100
    data = generate_data(
        rows=rows, rows_with_empty_siret=rows_with_empty_siret, rows_with_empty_email=rows_with_empty_email
    )
    file_path = sftp_directory.joinpath(faker.geiq_filename())
    with open(file_path, "wb") as xlsxfile:
        workbook = generate_excel_sheet(FILE_HEADERS, data)
        workbook.save(xlsxfile)
    with pytest.raises(AssertionError):
        df, info_stats = get_geiq_df(file_path)

    # Some missing emails
    rows = 185
    rows_with_empty_siret = 0
    rows_with_empty_email = 20
    data = generate_data(
        rows=rows, rows_with_empty_siret=rows_with_empty_siret, rows_with_empty_email=rows_with_empty_email
    )
    file_path = sftp_directory.joinpath(faker.geiq_filename())
    with open(file_path, "wb") as xlsxfile:
        workbook = generate_excel_sheet(FILE_HEADERS, data)
        workbook.save(xlsxfile)
    df, info_stats = get_geiq_df(file_path)
    assert df.shape == (rows - rows_with_empty_email, 8)
    assert info_stats == {
        "rows_in_file": rows,
        "rows_with_a_siret": rows,
        "rows_after_deduplication": rows,
        "rows_with_empty_email": rows_with_empty_email,
    }

    # Too many missing sirets
    rows = 185
    rows_with_empty_siret = 100
    rows_with_empty_email = 0
    data = generate_data(
        rows=rows, rows_with_empty_siret=rows_with_empty_siret, rows_with_empty_email=rows_with_empty_email
    )
    file_path = sftp_directory.joinpath(faker.geiq_filename())
    with open(file_path, "wb") as xlsxfile:
        workbook = generate_excel_sheet(FILE_HEADERS, data)
        workbook.save(xlsxfile)
    with pytest.raises(AssertionError):
        df, info_stats = get_geiq_df(file_path)

    # Duplicated rows
    rows = 250
    rows_with_empty_siret = 0
    rows_with_empty_email = 0
    duplicated_sirets = 20
    data = generate_data(
        rows=rows,
        rows_with_empty_siret=rows_with_empty_siret,
        rows_with_empty_email=rows_with_empty_email,
        duplicated_sirets=duplicated_sirets,
    )
    file_path = sftp_directory.joinpath(faker.geiq_filename())
    with open(file_path, "wb") as xlsxfile:
        workbook = generate_excel_sheet(FILE_HEADERS, data)
        workbook.save(xlsxfile)
    df, info_stats = get_geiq_df(file_path)
    assert df.shape == (rows - duplicated_sirets, 8)
    assert info_stats == {
        "rows_in_file": rows,
        "rows_with_a_siret": rows,
        "rows_after_deduplication": rows - duplicated_sirets,
        "rows_with_empty_email": rows_with_empty_email,
    }
