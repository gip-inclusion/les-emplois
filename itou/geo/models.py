import django.contrib.gis.geos as gis_geos
from django.contrib.gis.db import models as gis_models
from django.db import models

import itou.geo.enums as enums


class QPVQuerySet(models.QuerySet):
    def in_qpv(self, geom: gis_geos.GEOSGeometry):
        # QPV don't overlap
        return self.filter(geometry__contains=geom).first()


class QPV(models.Model):
    """
    QPV: Quartier de la Politique de la Ville
    Source: https://sig.ville.gouv.fr/atlas/QP
    Last update: 2022
    """

    code = models.CharField(verbose_name="code", max_length=8)
    name = models.CharField(verbose_name="référence", max_length=254)
    communes_info = models.CharField(verbose_name="nom des communes du QPV", max_length=254)
    geometry = gis_models.MultiPolygonField(verbose_name="contour géométrique du QPV")

    objects = QPVQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["code"]),
            # add GIS indexes (PG14+) should the need arise
        ]

        verbose_name = "quartier de la politique de la ville"
        verbose_name_plural = "quartiers de la politique de la ville"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def __repr__(self) -> str:
        return f"<pk={self.pk}, code={self.code},  name={self.name}>"

    def __contains__(self, geom: gis_geos.GEOSGeometry) -> bool:
        return getattr(self, "geometry").contains(geom)

    @classmethod
    def in_qpv(cls, obj_with_geometry, geom_field="geom"):
        """
        Get matching QPV in DB if given geometry is contained into QPV shape.

        The 'contained' field is a geometry, i.e. not only points can be used (polygons, multi-polygons..).

        Default field name for object geometry is 'geom' by GIS convention,
        even if QPV model object was created for `users.User` model (which has a `coords` field).
        """
        coords = getattr(obj_with_geometry, geom_field, None)

        if not coords:
            raise ValueError(f"No '{geom_field}' field found")

        if not isinstance(coords, gis_geos.GEOSGeometry):
            raise ValueError(f"{geom_field} is not a Geometry")

        return QPV.objects.in_qpv(coords)


class ZRRQuerySet(models.QuerySet):
    # .get() : ZRR classification is unique for a given INSEE code

    def in_zrr(self):
        return self.filter(status=enums.ZRRStatus.IN_ZRR)

    def not_in_zrr(self):
        return self.filter(status=enums.ZRRStatus.NOT_IN_ZRR)

    def partially_in_zrr(self):
        return self.filter(status=enums.ZRRStatus.PARTIALLY_IN_ZRR)


class ZRR(models.Model):
    """
    ZRR: Zone de Revitalisation Rurale
    Source: https://www.data.gouv.fr/en/datasets/zones-de-revitalisation-rurale-zrr/#resources
    Last update: 2021
    """

    insee_code = models.CharField(verbose_name="code INSEE de la commune", max_length=5)
    status = models.CharField(verbose_name="classement en ZRR", choices=enums.ZRRStatus.choices, max_length=2)

    objects = ZRRQuerySet.as_manager()

    class Meta:
        indexes = (
            models.Index(fields=["insee_code"]),
            models.Index(fields=["status"]),
        )
        verbose_name = "classification en Zone de Revitalisation Rurale (ZRR)"
        verbose_name_plural = "classifications en Zone de Revitalisation Rurale (ZRR)"

    def __str__(self) -> str:
        return f"{self.insee_code} - {self.status}"

    def __repr__(self) -> str:
        return f"<pk={self.pk}, insee_code={self.insee_code},  status={self.status}>"
