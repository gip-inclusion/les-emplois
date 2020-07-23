from django.utils.dateparse import parse_datetime

from .models import DataImport, ExternalUserData


# External user data from PE Connect API:
# * transform raw data from API
# * dispatch data into models


def import_pe_external_user_data(user, data):
    # User part can be directly "inserted" in to the model
    user.birthdate = user.birthdate or parse_datetime(data.get("dateDeNaissance"))
    user.address_line_1 = "" or user.address_line_1 or data.get("adresse4")
    # FIXME: WTF user.address_line_2 = '' or user.address_line_2 or data.get("adresse2")
    user.post_code = user.post_code or data.get("codePostal")
    user.city = user.city or data.get("libelleCommune")
    # ...
    user.save()

    # Save import metadata
    data_import = DataImport(user=user, status=DataImport.STATUS_OK, source=DataImport.DATA_SOURCE_PE_CONNECT)
    data_import.save()

    external_user_data = [
        ExternalUserData(key=ExternalUserData.KEY_IS_PE_JOBSEEKER, value=data.get("is_pe_jobseeker ", False)),
        ExternalUserData(
            key=ExternalUserData.KEY_HAS_MINIMAL_SOCIAL_ALLOWANCE,
            value=data.get("beneficiairePrestationSolidarite", False),
        ),
        ExternalUserData(key="adresse4", value=data.get("adresse4")),
    ]

    for data in external_user_data:
        data.data_import = data_import

    # FIXME: set correct import status
    ExternalUserData.objects.bulk_create(external_user_data)
