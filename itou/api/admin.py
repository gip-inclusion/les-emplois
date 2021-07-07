from rest_framework.authtoken.admin import TokenAdmin


# Patching TokenAdmin for all sub-APIs
# Avoids listing all users when updating auth token via admin
# See: https://www.django-rest-framework.org/api-guide/authentication/#tokenauthentication
TokenAdmin.raw_id_fields = ("user",)
