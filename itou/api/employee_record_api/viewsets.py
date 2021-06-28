from rest_framework import viewsets
from rest_framework.authentication import TokenAuthentication

from itou.employee_record.models import EmployeeRecord
from itou.employee_record.serializers import EmployeeRecordSerializer
from itou.siaes.models import SiaeMembership


class EmployeeRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Basic viewset for employee records:
    - list
    - detail
    - read-only
    """

    # If no queryset class paramter is given (overiding f.i.)
    # a `basename` parameter must be set on the router
    # See: https://www.django-rest-framework.org/api-guide/routers/

    serializer_class = EmployeeRecordSerializer
    # authentication_classes = [TokenAuthentication]

    def get_queryset(self):
        queryset = EmployeeRecord.objects.full_fetch().sent()

        # employee record API will return objects related to
        # all SIAE memberships of authenticated user
        memberships = SiaeMembership.objects.filter(user=self.request.user).values("siae")

        return queryset.filter(job_application__to_siae__in=memberships)
