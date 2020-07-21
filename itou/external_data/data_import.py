from django.utils.dateparse import parse_datetime

from . import models


# External user data from PE Connect API:
# * transform raw data from API
# * dispatch data into models


def import_pe_external_user_data(user, data):
    # User part
    user.birthdate = user.birthdate or parse_datetime(data.get("dateDeNaissance"))
    user.address_line_1 = "" or user.address_line_1 or data.get("adresse4")
    # FIXME: WTF user.address_line_2 = '' or user.address_line_2 or data.get("adresse2")
    user.post_code = user.post_code or data.get("codePostal")
    user.city = user.city or data.get("libelleCommune")
    # ...
    user.save()

    # Save import metadata

    # FIXME: set correct import status
    pe_extra_data = models.ExternalUserData(user=user, status=models.ExternalUserData.STATUS_OK)
    pe_extra_data.has_social_allowance = data.get("beneficiairePrestationSolidarite", False)
    pe_extra_data.is_pe_jobseeker = data.get("is_pe_jobseeker ", False)

    pe_extra_data.save()
