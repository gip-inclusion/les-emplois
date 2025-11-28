from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response

from itou.api.auth import ServiceTokenAuthentication
from itou.api.nexus.serializers import DeleteObjectSerializer, StructureSerializer, UserSerializer
from itou.nexus.models import Membership, Structure, User
from itou.nexus.utils import unique_id


class UsersView(generics.GenericAPIView):
    authentication_classes = [ServiceTokenAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = UserSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({}, status=status.HTTP_201_CREATED, headers={})

    def perform_create(self, serializer):
        validated_data = serializer.validated_data
        source = self.request.auth.service

        users = []
        memberships = []

        for user_data in validated_data:
            user_id = unique_id(user_data["source_id"], source)
            memberships_data = user_data.pop("memberships")
            for membership_data in memberships_data:
                structure_id = unique_id(membership_data["structure_id"], source)
                memberships.append(
                    Membership(source=source, user_id=user_id, structure_id=structure_id, role=membership_data["role"])
                )

            users.append(
                User(
                    source=source,
                    id=user_id,
                    kind=user_data["source_kind"],  # FIXME Use mapping
                    **user_data,
                )
            )

        # Filter out memberships on unknown structures
        # NB: no need to filter with source since ids are always prefixed with source
        structure_ids = list(
            Structure.objects.filter(id__in=[m.structure_id for m in memberships]).values_list("id", flat=True)
        )
        memberships = filter(lambda m: m.structure_id in structure_ids, memberships)

        # Write in database
        updated_at = timezone.now()
        users = User.objects.bulk_create(
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
        Membership.objects.bulk_create(
            memberships,
            update_conflicts=True,
            update_fields=["role", "updated_at"],
            unique_fields=["user", "structure"],
        )
        # Remove old memberships (they don't exist anymore)
        Membership.objects.filter(user__in=users, updated_at__lt=updated_at).delete()

    def delete(self, request, *args, **kwargs):
        serializer = DeleteObjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_delete(serializer)
        # Do we return a deleted / not found response ?
        return Response({}, status=status.HTTP_202_ACCEPTED, headers={})

    def perform_delete(self, serializer):
        User.objects.filter(source=self.request.auth.service, **serializer.validated_data).delete()


class StructureView(generics.GenericAPIView):
    authentication_classes = [ServiceTokenAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = StructureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({}, status=status.HTTP_201_CREATED, headers={})

    def perform_create(self, serializer):
        validated_data = serializer.validated_data
        validated_data["kind"] = validated_data["source_kind"]  # FIXME use mapping
        source = self.request.auth.service

        Structure.objects.update_or_create(
            source=source,
            id=unique_id(validated_data["source_id"], source),
            defaults=validated_data,
        )

    def delete(self, request, *args, **kwargs):
        serializer = DeleteObjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_delete(serializer)
        # Do we return a deleted / not found response ?
        return Response({}, status=status.HTTP_202_ACCEPTED, headers={})

    def perform_delete(self, serializer):
        Structure.objects.filter(source=self.request.auth.service, **serializer.validated_data).delete()
