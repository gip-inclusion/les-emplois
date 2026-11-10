import importlib
import os

import pytest

import itou.utils.auth
from itou.utils.auth import get_client_ip


CLIENT_IPS_TO_TEST = ["82.64.254.93", "2a01:e0a:11d4:ca10::8481:4731"]


def test_get_client_ip_fallback(rf):
    request = rf.get("/")
    del request.META["REMOTE_ADDR"]
    assert get_client_ip(request) is None


@pytest.mark.parametrize("real_client_ip", CLIENT_IPS_TO_TEST)
def test_get_client_ip_fallback_to_remote_addr(rf, real_client_ip):
    request = rf.get("/", REMOTE_ADDR=real_client_ip)
    assert get_client_ip(request) == real_client_ip


@pytest.mark.parametrize("real_client_ip", CLIENT_IPS_TO_TEST)
def test_get_client_ip_no_clever_cloud_whitelist(rf, real_client_ip):
    request = rf.get("/", headers={"X-Forwarded-For": real_client_ip}, REMOTE_ADDR="10.0.0.1")
    assert get_client_ip(request) == real_client_ip


@pytest.mark.parametrize("real_client_ip", CLIENT_IPS_TO_TEST)
def test_get_client_ip_picks_the_rightmost_one(rf, real_client_ip):
    request = rf.get("/", headers={"X-Forwarded-For": f",::1,,   ,  {real_client_ip}  "}, REMOTE_ADDR="10.0.0.1")
    assert get_client_ip(request) == real_client_ip


@pytest.mark.parametrize(
    "x_forwarded_for, real_client_ip",
    [
        (x_forwarded_for.format(real_client_ip), real_client_ip)
        for x_forwarded_for in (
            "{}",
            ",::1,{}",
            "10.0.0.1,{},10.0.0.2",
            "10.0.0.1, {}, 10.0.0.2",
            "  10.0.0.1  ,  {}  ,  10.0.0.2  ",
            "10.0.0.1,2001::7348,{},2001::7348,10.0.0.2",
            "10.0.0.1, ::1, 2001::7348, {},10.0.0.2, 10.0.0.4",
            "10.0.0.1, ::1, 2001::7348, {},10.0.0.2, 10.0.0.4, 10.0.0.5",
        )
        for real_client_ip in CLIENT_IPS_TO_TEST
    ],
)
def test_get_client_ip_with_clever_proxies(rf, monkeypatch, x_forwarded_for, real_client_ip):
    monkeypatch.setitem(
        os.environ,
        "CC_REVERSE_PROXY_IPS",
        "10.0.0.1, 10.0.0.2, 10.0.0.3,2001::7348,10.0.0.4,10.0.0.5 ",
    )
    importlib.reload(itou.utils.auth)  # To re-read os.environ in the CC_REVERSE_PROXY_IPS global
    request = rf.get("/", headers={"X-Forwarded-For": x_forwarded_for}, REMOTE_ADDR="10.0.0.1")
    assert get_client_ip(request) == real_client_ip
