from itou.api.job_application_api.schema import (
    job_application_search_request_example,
    job_application_search_response_valid_example,
)
from itou.api.job_application_api.serializers import (
    JobApplicationSearchRequestSerializer,
    JobApplicationSearchResponseSerializer,
    JobDescriptionSerializer,
)


def test_job_application_search_request_example():
    """
    Ensure example payload is in sync with current request serializer
    """
    assert job_application_search_request_example.value.keys() == JobApplicationSearchRequestSerializer().fields.keys()


def test_job_application_search_response_example():
    """
    Ensure example payload is in sync with current response serializer
    """
    assert (
        job_application_search_response_valid_example.value["results"][0].keys()
        == JobApplicationSearchResponseSerializer().fields.keys()
    )
    assert (
        job_application_search_response_valid_example.value["results"][1]["contrat_poste_retenu"].keys()
        == JobDescriptionSerializer().fields.keys()
    )
    assert (
        job_application_search_response_valid_example.value["results"][1]["orientation_postes_recherches"][0].keys()
        == JobDescriptionSerializer().fields.keys()
    )
