import datetime


# SFTP path: Where to put new employee records for ASP validation
ASP_FS_REMOTE_UPLOAD_DIR = "depot"
# SFTP path: Where to get submitted employee records validation feedback
ASP_FS_REMOTE_DOWNLOAD_DIR = "retrait"

# Employee record data archiving / pruning:
# "Proof of record" model field is erased after this delay (in days)
EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS = 13 * 30

# This is the official and final production phase date of the employee record feature.
# It is used as parameter to filter the eligible job applications for the feature.
# (no job application before this date can be used for this feature)
EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE = datetime.datetime(2021, 9, 27, tzinfo=datetime.timezone.utc)
