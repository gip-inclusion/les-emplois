from rest_framework import viewsets

from itou.employee_record.models import EmployeeRecord
from itou.employee_record.serializers import EmployeeRecordSerializer


class EmployeeRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Basic viewset for employee records:
    - list
    - detail
    - read-only
    """

    queryset = EmployeeRecord.objects.full_fetch().sent()
    serializer_class = EmployeeRecordSerializer
