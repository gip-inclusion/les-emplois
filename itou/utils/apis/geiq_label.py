import enum
import json

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


API_TIMEOUT_SECONDS = 5.0


class LabelAPIError(Exception):
    pass


class LabelCommand(enum.StrEnum):
    Salarie = "Salarie"
    SalarieContrat = "SalarieContrat"
    SalariePreQualification = "SalariePreQualification"
    DownloadCompte = "DownloadCompte"
    Geiq = "Geiq"
    GeiqPrestation = "GeiqPrestation"
    SynthesePDF = "SynthesePDF"
    TauxGeiq = "TauxGeiq"


class LabelApiClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": token},
            timeout=API_TIMEOUT_SECONDS,
        )

    def _command(self, command, **params):
        command = LabelCommand(command)
        if command in (LabelCommand.DownloadCompte, LabelCommand.SynthesePDF):
            raise ValueError(f"{command} does not return JSON data")
        try:
            response_data = (
                self.client.get(
                    f"rest/{command}",
                    params=params,
                )
                .raise_for_status()
                .json()
            )
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise LabelAPIError("Error requesting Label API") from exc
        if response_data.get("status") != "Success":
            raise LabelAPIError(f"Received response with status={response_data.get('Status')}")
        return response_data["result"]

    def get_all_geiq(self, *, page_size=100):
        data = []
        p = 1
        while new_values := self._command(LabelCommand.Geiq, sort="geiq.id", n=page_size, p=p):
            data.extend(new_values)
            if len(new_values) != page_size:
                break
            p += 1
        return data

    def get_taux_geiq(self, *, geiq_id=None, page_size=100):
        data = []
        if geiq_id:
            data.extend(self._command(LabelCommand.TauxGeiq, where=f"geiq,=,{geiq_id}"))
        else:
            p = 1
            while new_values := self._command(LabelCommand.TauxGeiq, sort="geiq.id", n=page_size, p=p):
                data.extend(new_values)
                if len(new_values) != page_size:
                    break
                p += 1
        return data

    def get_compte_pdf(self, *, geiq_id):
        try:
            response_data = self.client.get(
                f"rest/{LabelCommand.DownloadCompte}",
                params={"id": geiq_id},
            ).raise_for_status()
        except httpx.HTTPError as exc:
            raise LabelAPIError("Error requesting Label API") from exc
        if response_data.headers["content-type"] != "application/pdf":
            raise LabelAPIError(f"Unexpected content-type: {response_data.headers.get('content-type')}")
        return response_data.content

    def get_synthese_pdf(self, *, geiq_id):
        try:
            response_data = self.client.get(
                f"rest/{LabelCommand.SynthesePDF}",
                params={"id": geiq_id},
            ).raise_for_status()
        except httpx.HTTPError as exc:
            raise LabelAPIError("Error requesting Label API") from exc
        if response_data.headers["content-type"] != "application/pdf":
            raise LabelAPIError(f"Unexpected content-type: {response_data.headers.get('content-type')}")
        return response_data.content

    def get_all_contracts(self, geiq_id, *, page_size=100):
        data = []
        p = 1
        expected_nb = self._command(
            LabelCommand.SalarieContrat, join="salariecontrat.salarie,s", where=f"s.geiq,=,{geiq_id}", count=True
        )
        while new_values := self._command(
            LabelCommand.SalarieContrat,
            join="salariecontrat.salarie,s",
            where=f"s.geiq,=,{geiq_id}",
            sort="salariecontrat.id",
            n=page_size,
            p=p,
        ):
            data.extend(new_values)
            if len(new_values) != page_size:
                break
            p += 1
        assert len(data) == expected_nb
        return data

    def get_all_prequalifications(self, geiq_id, *, page_size=100):
        data = []
        p = 1
        expected_nb = self._command(
            LabelCommand.SalariePreQualification,
            join="salarieprequalification.salarie,s",
            where=f"s.geiq,=,{geiq_id}",
            count=True,
        )
        while new_values := self._command(
            LabelCommand.SalariePreQualification,
            join="salarieprequalification.salarie,s",
            where=f"s.geiq,=,{geiq_id}",
            sort="salarieprequalification.id",
            n=page_size,
            p=p,
        ):
            data.extend(new_values)
            if len(new_values) != page_size:
                break
            p += 1
        assert len(data) == expected_nb
        return data


def get_client():
    if not settings.API_GEIQ_LABEL_BASE_URL or not settings.API_GEIQ_LABEL_TOKEN:
        raise ImproperlyConfigured("Missing configuration for Label API")
    return LabelApiClient(
        base_url=settings.API_GEIQ_LABEL_BASE_URL,
        token=settings.API_GEIQ_LABEL_TOKEN,
    )
