import datetime

from itou.companies.enums import CompanyKind


# SFTP path: Where to put new employee records for ASP validation
ASP_FS_REMOTE_UPLOAD_DIR = "depot"
# SFTP path: Where to get submitted employee records validation feedback
ASP_FS_REMOTE_DOWNLOAD_DIR = "retrait"

# This is the official and final production phase date of the employee record feature.
# It is used as parameter to filter the eligible job applications for the feature.
# (no job application before this date can be used for this feature)
EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE = datetime.datetime(2021, 9, 27, tzinfo=datetime.UTC)
EMPLOYEE_RECORD_EITI_AVAILABILITY_DATE = datetime.datetime(2024, 3, 25, tzinfo=datetime.UTC)


def get_availability_date_for_kind(kind):
    if kind == CompanyKind.EITI:
        return EMPLOYEE_RECORD_EITI_AVAILABILITY_DATE
    return EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
