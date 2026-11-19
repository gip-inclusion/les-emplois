import dataclasses
import logging
import uuid
from typing import Literal
from urllib.parse import urljoin

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)


# Keep in sync with https://github.com/gip-inclusion/api-relay-cnav/blob/main/api_relay_cnav/utils/interops.py
@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Name:
    accented: str | None
    filtered: str | None

    @classmethod
    def from_dict(cls, data):
        return cls(accented=data.get("accented"), filtered=data.get("filtered"))


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class FirstNames:
    accented: list[str]
    filtered: list[str]

    @classmethod
    def from_dict(cls, data):
        return cls(accented=data["accented"], filtered=data["filtered"])


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class PersonalInfos:
    number: str
    sex_code: Literal[1] | Literal[2] | None
    birth_date: str | None
    birth_place: str | None
    death_date: str | None
    number_history: list[str]

    birth_name: Name | None
    common_name: Name | None
    marital_name: Name | None

    first_names: FirstNames | None

    @classmethod
    def from_dict(cls, data):
        kwargs = {
            key: data.get(key)
            for key in [
                "number",
                "sex_code",
                "birth_date",
                "birth_place",
                "death_date",
            ]
        }
        kwargs["number_history"] = data.get("number_history", [])
        kwargs["first_names"] = (
            FirstNames.from_dict(data.get("first_names")) if data.get("first_names") is not None else None
        )
        for name_field in ["birth_name", "common_name", "marital_name"]:
            kwargs[name_field] = Name.from_dict(data.get(name_field)) if data.get(name_field) is not None else None
        return cls(**kwargs)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class InterOpsResult:
    # Slight adaptation vs api_relay_cnav version
    result_code: int
    result_label: str | None

    infos: PersonalInfos | None = None

    @classmethod
    def from_dict(cls, data):
        return cls(
            result_code=data["result_code"],
            result_label=data["result_label"],
            infos=PersonalInfos.from_dict(data["infos"]) if data.get("infos") else None,
        )


class CNAVRelayApiClient:
    def __init__(self, *, relay_url, relay_token, read_timeout=None) -> None:
        self.relay_token = relay_token
        self.relay_url = relay_url
        self._httpx_client = None
        self._timeout = httpx.Timeout(5, read=read_timeout if read_timeout is not None else 5)

    def __enter__(self):
        self._httpx_client = httpx.Client().__enter__()
        return self

    def __exit__(self, type, value, traceback):
        self._httpx_client.__exit__(type, value, traceback)

    def _get_httpx_client(self):
        return self._httpx_client or httpx.Client()

    def identity(
        self,
        *,
        number,
        name,
        first_names=None,
        sex_code=None,
        birth_date,
    ) -> InterOpsResult:
        request_uid = str(uuid.uuid4())
        logger.info("Sending request=%s to relay", request_uid)
        payload = {
            "request_uid": request_uid,
            "number": number,
            "name": name,
            "birth_date": birth_date.isoformat(),
        }
        if sex_code is not None:
            payload["sex_code"] = sex_code
        if first_names is not None:
            payload["first_names"] = first_names
        data = (
            self._get_httpx_client()
            .post(
                url=urljoin(self.relay_url, "identity/"),
                data=payload,
                headers={"Authorization": f"Token {self.relay_token}"},
                timeout=self._timeout,
            )
            .raise_for_status()
            .json()
        )
        return InterOpsResult.from_dict(data)


def get_client(*, read_timeout=None):
    return CNAVRelayApiClient(
        relay_url=settings.API_RELAY_CNAV["RELAY_URL"],
        relay_token=settings.API_RELAY_CNAV["RELAY_TOKEN"],
        read_timeout=read_timeout,
    )
