import logging

from django.utils import timezone
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
from itou.nexus.enums import USER_KIND_MAPPING
from itou.nexus.models import NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.nexus.utils import service_id


logger = logging.getLogger(__name__)


class NexusApiMixin:
    authentication_classes = [ServiceTokenAuthentication]

    @property
    def source(self):
        return self.request.auth.service


@extend_schema(exclude=True)
class UsersView(NexusApiMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        serializer = UserSerializer(data=request.data, many=True, source=self.source)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({}, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        validated_data = serializer.validated_data

        users = []
        memberships = []

        for user_data in validated_data:
            user_id = service_id(self.source, user_data["source_id"])
            memberships_data = user_data.pop("memberships")
            for membership_data in memberships_data:
                structure_id = service_id(self.source, membership_data["structure_id"])
                memberships.append(
                    NexusMembership(
                        source=self.source, user_id=user_id, structure_id=structure_id, role=membership_data["role"]
                    )
                )

            users.append(
                NexusUser(
                    source=self.source,
                    id=user_id,
                    kind=USER_KIND_MAPPING[self.source][user_data["source_kind"]],
                    **user_data,
                )
            )

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
        updated_at = timezone.now()
        users = NexusUser.objects.bulk_create(
            users,
            update_conflicts=True,
            update_fields=[
                "kind",
                "source_kind",
                "source_id",
                "first_name",
                "last_name",
                "email",
                "phone",
                "last_login",
                "auth",
                "updated_at",
            ],
            unique_fields=["id"],
        )
        NexusMembership.objects.bulk_create(
            filtered_memberships,
            update_conflicts=True,
            update_fields=["role", "updated_at"],
            unique_fields=["user", "structure"],
        )
        # Remove old memberships (they don't exist anymore)
        NexusMembership.objects.filter(user__in=users, updated_at__lt=updated_at).delete()

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
        serializer = StructureSerializer(source=self.source, data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({}, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        validated_data = serializer.validated_data

        structures = []

        for structure_data in validated_data:
            structures.append(
                NexusStructure(
                    source=self.source,
                    id=service_id(self.source, structure_data["source_id"]),
                    kind=structure_data["source_kind"],  # TODO: Add mapping
                    **structure_data,
                )
            )
        NexusStructure.objects.bulk_create(
            structures,
            update_conflicts=True,
            update_fields=[
                "kind",
                "source_kind",
                "source_id",
                "siret",
                "name",
                "phone",
                "email",
                "address_line_1",
                "address_line_2",
                "post_code",
                "city",
                "department",
                "accessibility",
                "description",
                "opening_hours",
                "source_link",
                "website",
                "updated_at",
            ],
            unique_fields=["id"],
        )

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
        return Response({"started_at": self.init_sync().isoformat()}, status=status.HTTP_200_OK)

    def init_sync(self):
        now = timezone.now()
        NexusRessourceSyncStatus.objects.update_or_create(
            service=self.source,
            defaults={"new_start_at": now},
            create_defaults={"service": self.source, "new_start_at": now},
        )
        return now


@extend_schema(exclude=True)
class SyncCompletedView(NexusApiMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        serializer = SyncCompletedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        started_at = serializer.validated_data["started_at"]
        if NexusRessourceSyncStatus.objects.filter(service=self.source, new_start_at=started_at).update(
            new_start_at=None, valid_since=started_at
        ):
            return Response({}, status=status.HTTP_200_OK)

        logger.warning("Got invalid start_at for source=%s", self.source, exc_info=True)
        return Response({}, status=status.HTTP_403_FORBIDDEN)
