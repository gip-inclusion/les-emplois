import datetime


def rsa_certified_mocker():
    mocked_data = {"status": "non_beneficiaire", "majoration": "null", "dateDebut": "null", "dateFin": "null"}
    is_certified = True
    certification_period = (datetime.datetime(1992, 11, 20), datetime.datetime(1993, 2, 20))
    return (mocked_data, is_certified, certification_period)
    # return mock.patch(
    # "itou.utils.apis.api_particulier.APIParticulierClient.revenu_solidarite_active",
    # return_value=(mocked_data, is_certified, certification_period),
    # )
