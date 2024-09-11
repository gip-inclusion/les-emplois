import enum


class DatumKey(enum.StrEnum):
    DATA_UPDATED_AT = "data_updated_at"
    FLUX_IAE_DATA_UPDATED_AT = "flux_iae_data_updated_at"
    JOB_SEEKER_STILL_SEEKING_AFTER_30_DAYS = "job_seeker_still_seeking_after_30_days"
    JOB_SEEKER_STILL_SEEKING_AFTER_30_DAYS_BY_DEPARTMENTS = "job_seeker_still_seeking_after_30_days_by_departments"
    JOB_SEEKER_STILL_SEEKING_AFTER_30_DAYS_BY_REGIONS = "job_seeker_still_seeking_after_30_days_by_regions"
    JOB_APPLICATION_WITH_HIRING_DIFFICULTY = "job_application_with_hiring_difficulty"
    JOB_APPLICATION_WITH_HIRING_DIFFICULTY_BY_DEPARTMENTS = "job_application_with_hiring_difficulty_by_departments"
    JOB_APPLICATION_WITH_HIRING_DIFFICULTY_BY_REGIONS = "job_application_with_hiring_difficulty_by_regions"
    JOB_APPLICATION_ACCEPTED_YEAR_TO_DATE = "job_application_accepted_year_to_date"
    JOB_APPLICATION_ACCEPTED_YEAR_TO_DATE_BY_DEPARTMENTS = "job_application_accepted_year_to_date_by_departments"
    JOB_APPLICATION_ACCEPTED_YEAR_TO_DATE_BY_REGIONS = "job_application_accepted_year_to_date_by_regions"
    RATE_OF_ACCEPTED_JOB_APPLICATIONS_PRESCRIBED_BY_AHI = "rate_of_accepted_job_applications_prescribed_by_ahi"
    RATE_OF_ACCEPTED_JOB_APPLICATIONS_PRESCRIBED_BY_AHI_BY_DEPARTMENTS = (
        "rate_of_accepted_job_applications_prescribed_by_ahi_by_departments"
    )
    RATE_OF_ACCEPTED_JOB_APPLICATIONS_PRESCRIBED_BY_AHI_BY_REGIONS = (
        "rate_of_accepted_job_applications_prescribed_by_ahi_by_regions"
    )

    def grouped_by(self, group_by):
        return self.__class__[f"{self.name}_BY_{group_by.upper()}S"]
