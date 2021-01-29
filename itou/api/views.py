from rest_framework import generics
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated

from itou.api.serializers import SiaeSerializer
from itou.siaes.models import Siae


class SiaeList(generics.ListAPIView):
    serializer_class = SiaeSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        This view returns the list of all the siaes the currently authenticated user is a member of.
        """
        user = self.request.user
        # Order by pk to solve pagination warning.
        return Siae.objects.filter(members=user).order_by("pk")
