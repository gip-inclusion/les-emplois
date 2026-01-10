import logging

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response

from itou.api.auth import ServiceTokenAuthentication
from itou.api.nexus.serializers import (
    DeleteObjectSerializer,
    StructureSerializer,
    SyncCompletedSerializer,
    UserSerializer,
)
from itou.nexus import utils as nexus_utils
from itou.nexus.models import NexusMembership, NexusStructure, NexusUser


logger = logging.getLogger(__name__)


class NexusApiMixin:
    authentication_classes = [ServiceTokenAuthentication]

    @property
    def source(self):
        return self.request.auth.service


@extend_schema(exclude=True)
class UsersView(NexusApiMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        serializer = UserSerializer(data=request.data, many=True, context={"source": self.source})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({}, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        validated_data = serializer.validated_data

        users = []
        memberships = []

        for user_data in validated_data:
            memberships_data = user_data.pop("memberships")
            users.append(nexus_utils.build_user(user_data, self.source))

            for membership_data in memberships_data:
                membership_data["user_id"] = user_data["source_id"]
                memberships.append(nexus_utils.build_membership(membership_data, self.source))

        # Filter out memberships on unknown structures
        # NB: no need to filter with source since ids are always prefixed with source
        structure_ids = set(
            NexusStructure.objects.filter(id__in=[m.structure_id for m in memberships]).values_list("id", flat=True)
        )
        filtered_memberships = []
        for membership in memberships:
            if membership.structure_id in structure_ids:
                filtered_memberships.append(membership)
            else:
                logger.warning("NexusAPI: Ignoring memberships for structure=%s", membership.structure_id)

        # Write in database
        nexus_utils.sync_users(users)
        nexus_utils.sync_memberships(filtered_memberships)
        # Remove memberships we didn't receive for those users, they don't exist anymore
        NexusMembership.objects.filter(user__in=users).exclude(id__in=[m.pk for m in filtered_memberships]).delete()

    def delete(self, request, *args, **kwargs):
        serializer = DeleteObjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if self.perform_delete(serializer):
            return Response({}, status=status.HTTP_200_OK)
        return Response({}, status=status.HTTP_404_NOT_FOUND)

    def perform_delete(self, serializer):
        deleted, _details = NexusUser.objects.filter(source=self.source, **serializer.validated_data).delete()
        return deleted


@extend_schema(exclude=True)
class StructuresView(NexusApiMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        serializer = StructureSerializer(data=request.data, many=True, context={"source": self.source})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({}, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        validated_data = serializer.validated_data
        structures = [nexus_utils.build_structure(structure_data, self.source) for structure_data in validated_data]
        nexus_utils.sync_structures(structures)

    def delete(self, request, *args, **kwargs):
        serializer = DeleteObjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if self.perform_delete(serializer):
            return Response({}, status=status.HTTP_200_OK)
        return Response({}, status=status.HTTP_404_NOT_FOUND)

    def perform_delete(self, serializer):
        deleted, _details = NexusStructure.objects.filter(source=self.source, **serializer.validated_data).delete()
        return deleted


@extend_schema(exclude=True)
class SyncStartView(NexusApiMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        return Response(
            {"started_at": nexus_utils.init_full_sync(self.source).isoformat()},
            status=status.HTTP_200_OK,
        )


@extend_schema(exclude=True)
class SyncCompletedView(NexusApiMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        serializer = SyncCompletedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        started_at = serializer.validated_data["started_at"]
        if nexus_utils.complete_full_sync(self.source, started_at):
            return Response({}, status=status.HTTP_200_OK)

        logger.warning("Got invalid start_at for source=%s", self.source, exc_info=True)
        return Response({}, status=status.HTTP_403_FORBIDDEN)
