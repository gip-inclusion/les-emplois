import logging

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response

from itou.api.auth import ServiceTokenAuthentication
from itou.api.nexus.serializers import (
    DeleteObjectSerializer,
    MembershipSerializer,
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


class NexusApiObjectsMixin(NexusApiMixin):
    serializer = None
    model_class = None
    build_obj = None
    sync_objs = None

    def post(self, request, *args, **kwargs):
        serializer = self.serializer(data=request.data, many=True, context={"source": self.source})
        serializer.is_valid(raise_exception=True)
        objs = [self.build_obj(data, self.source) for data in serializer.validated_data]
        self.sync_objs(objs)
        return Response({}, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        serializer = DeleteObjectSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.perform_delete(serializer)
        return Response({}, status=status.HTTP_200_OK)

    def perform_delete(self, serializer):
        source_ids = [data["source_id"] for data in serializer.validated_data]
        deleted, _details = self.model_class.objects.filter(source=self.source, source_id__in=source_ids).delete()
        return deleted


@extend_schema(exclude=True)
class UsersView(NexusApiObjectsMixin, generics.GenericAPIView):
    serializer = UserSerializer
    model_class = NexusUser
    build_obj = staticmethod(nexus_utils.build_user)
    sync_objs = staticmethod(nexus_utils.sync_users)


@extend_schema(exclude=True)
class MembershipsView(NexusApiObjectsMixin, generics.GenericAPIView):
    serializer = MembershipSerializer
    model_class = NexusMembership
    build_obj = staticmethod(nexus_utils.build_membership)
    sync_objs = staticmethod(nexus_utils.sync_memberships)


@extend_schema(exclude=True)
class StructuresView(NexusApiObjectsMixin, generics.GenericAPIView):
    serializer = StructureSerializer
    model_class = NexusStructure
    build_obj = staticmethod(nexus_utils.build_structure)
    sync_objs = staticmethod(nexus_utils.sync_structures)


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
