from itou.eligibility.models import EligibilityDiagnosis


def iae_diagnosis_for_user(user, job_application):
    if not job_application.to_company.is_subject_to_eligibility_rules:
        return None
    if job_application.eligibility_diagnosis:
        return job_application.eligibility_diagnosis
    kwargs = {"job_seeker": job_application.job_seeker}
    if user.is_employer or user.is_job_seeker:
        kwargs["for_siae"] = job_application.to_company
    return EligibilityDiagnosis.objects.last_considered_valid(**kwargs)


def show_afpa_ad(user):
    postcode = user.jobseeker_profile.hexa_post_code or user.post_code
    return postcode[:2] in [
        # Hauts-de-france
        "02",
        "59",
        "60",
        "62",
        "80",
        # Nouvelle aquitaine
        "16",
        "17",
        "19",
        "23",
        "24",
        "33",
        "40",
        "47",
        "64",
        "79",
        "86",
        "87",
    ]
