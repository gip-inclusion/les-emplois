import dataclasses
import re

from django.conf import settings
from drf_spectacular.generators import SchemaGenerator

from itou.api.applicants_api.views import tag_description as applicants_tag_description
from itou.api.employee_record_api.viewsets import tag_description as employee_record_tag_description
from itou.api.geiq.views import tag_description as geiq_tag_description
from itou.api.job_application_api.views import tag_description as job_application_tag_description
from itou.api.token_auth.views import tag_description as token_auth_tag_description


@dataclasses.dataclass(frozen=True)
class Documentation:
    slug: str
    title: str
    # Displayed at the top of the documentation.
    description: str
    # First path segment after `SCHEMA_PATH_PREFIX`, which is also the OpenAPI tag of the endpoint.
    tags: tuple[str, ...]

    def includes(self, path):
        return get_tag(path) in self.tags


DOCUMENTATIONS = {
    documentation.slug: documentation
    for documentation in [
        Documentation(
            slug="employeurs",
            title="API employeurs",
            description="API à destination des employeurs.\n\n"
            "Les permissions requises pour les différentes ressources sont indiquées à leur niveau.",
            tags=("candidats", "employee-records", "embauches-geiq", "token-auth"),
        ),
        Documentation(
            slug="conseils-departementaux",
            title="API conseils départementaux",
            description="APIs à destination des conseils départementaux.",
            tags=("candidatures",),
        ),
        Documentation(
            slug="siae",
            title="API publique",
            description="API publique de La plateforme de l’inclusion.\n\n"
            "Ces données sont mises à disposition de tous.",
            tags=("siaes",),
        ),
        Documentation(
            slug="interne",
            title="APIs internes",
            description="Vous êtes dans la documentation des APIs internes de la plateforme de l’inclusion/\n\n"
            "Ces APIs sont uniquement accessibles par les différents services de la plateforme de l’inclusion.",
            tags=("insertion", "marche", "data-inclusion"),
        ),
    ]
}


# Markdown displayed at the top of the section of a tag, in the documentation listing this tag.
TAG_DESCRIPTIONS = {
    "candidats": applicants_tag_description,
    "employee-records": employee_record_tag_description,
    "embauches-geiq": geiq_tag_description,
    "candidatures": job_application_tag_description,
    "token-auth": token_auth_tag_description,
}


def get_tag(path):
    match = re.match(rf"^{settings.SPECTACULAR_SETTINGS['SCHEMA_PATH_PREFIX']}/([^/]+)", path)
    return match.group(1) if match else None


class DocumentationSchemaGenerator(SchemaGenerator):
    """Restrict the OpenAPI schema to the endpoints of a single documentation."""

    def __init__(self, *args, documentation, **kwargs):
        super().__init__(*args, **kwargs)
        self.documentation = documentation

    def _initialise_endpoints(self):
        super()._initialise_endpoints()
        self.endpoints = [endpoint for endpoint in self.endpoints if self.documentation.includes(endpoint[0])]

    def get_schema(self, request=None, public=False):
        schema = super().get_schema(request=request, public=public)
        schema["info"]["title"] = f"{self.documentation.title} - {schema['info']['title']}"
        schema["info"]["description"] = self.documentation.description
        # Introduction displayed at the top of each tag section, in the order of the documentation tags.
        if tags := [
            {"name": tag, "description": TAG_DESCRIPTIONS[tag]}
            for tag in self.documentation.tags
            if tag in TAG_DESCRIPTIONS
        ]:
            schema["tags"] = tags
        return schema
