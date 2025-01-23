from itou.eligibility.enums import AuthorKind
from itou.users.enums import UserKind


def build_iae_diag_post_data(author, job_seeker, with_administrative_criteria=True):
    post_data = {
        "job_seeker": job_seeker.pk,
        "author": author.pk,
        "author_kind": author.kind,
        "author_prescriber_organization": "",
        "author_siae": "",
        "_save": "Enregistrer",
        "selected_administrative_criteria-TOTAL_FORMS": "0",
        "selected_administrative_criteria-INITIAL_FORMS": "0",
        "selected_administrative_criteria-MIN_NUM_FORMS": "0",
        "selected_administrative_criteria-MAX_NUM_FORMS": "1000",
        "jobapplication_set-TOTAL_FORMS": "0",
        "jobapplication_set-INITIAL_FORMS": "0",
        "jobapplication_set-MIN_NUM_FORMS": "0",
        "jobapplication_set-MAX_NUM_FORMS": "0",
        "approval_set-TOTAL_FORMS": "0",
        "approval_set-INITIAL_FORMS": "0",
        "approval_set-MIN_NUM_FORMS": "0",
        "approval_set-MAX_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-0-remark": "",
        "utils-pksupportremark-content_type-object_id-0-id": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
    }
    if author.kind == UserKind.EMPLOYER:
        post_data["author_siae"] = author.companymembership_set.get().company_id
    elif author.kind == UserKind.PRESCRIBER:
        post_data["author_prescriber_organization"] = author.prescribermembership_set.get().organization_id

    if with_administrative_criteria:
        post_data |= {
            "selected_administrative_criteria-TOTAL_FORMS": "1",
            "selected_administrative_criteria-0-id": "",
            "selected_administrative_criteria-0-eligibility_diagnosis": "",
            "selected_administrative_criteria-0-administrative_criteria": "1",
        }
    return post_data


def build_geiq_diag_post_data(author, job_seeker, with_administrative_criteria=True):
    post_data = {
        "job_seeker": job_seeker.pk,
        "author": author.pk,
        "author_kind": author.kind if author.kind == UserKind.PRESCRIBER else AuthorKind.GEIQ,
        "author_prescriber_organization": "",
        "author_geiq": "",
        "_save": "Enregistrer",
        "selected_administrative_criteria-TOTAL_FORMS": "0",
        "selected_administrative_criteria-INITIAL_FORMS": "0",
        "selected_administrative_criteria-MIN_NUM_FORMS": "0",
        "selected_administrative_criteria-MAX_NUM_FORMS": "1000",
        "job_applications-TOTAL_FORMS": "0",
        "job_applications-INITIAL_FORMS": "0",
        "job_applications-MIN_NUM_FORMS": "0",
        "job_applications-MAX_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-0-remark": "",
        "utils-pksupportremark-content_type-object_id-0-id": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
    }
    if author.kind == UserKind.EMPLOYER:
        post_data["author_geiq"] = author.companymembership_set.get().company_id
    elif author.kind == UserKind.PRESCRIBER:
        post_data["author_prescriber_organization"] = author.prescribermembership_set.get().organization_id

    if with_administrative_criteria:
        post_data |= {
            "selected_administrative_criteria-TOTAL_FORMS": "1",
            "selected_administrative_criteria-0-id": "",
            "selected_administrative_criteria-0-eligibility_diagnosis": "",
            "selected_administrative_criteria-0-administrative_criteria": "1",
        }
    return post_data
