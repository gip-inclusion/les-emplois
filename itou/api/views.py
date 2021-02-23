from rest_framework import generics
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated

from itou.api.serializers import DummyEmployeeRecordSerializer
from itou.job_applications.models import JobApplication


class DummyEmployeeRecordList(generics.ListAPIView):
    """
    Return dummy (fake) employee record objects for testing by external software editors.
    """

    serializer_class = DummyEmployeeRecordSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Return the same 25 job applications whatever the user.
        The DummyEmployeeRecordSerializer will replace these objects with raw randomized jsons.
        25 is slightly more than the page size (50) so that pagination can be tested.
        Order by pk to solve pagination warning.
        """
        return JobApplication.objects.order_by("pk")[:25]
