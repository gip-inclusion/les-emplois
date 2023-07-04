# Following tests are made with `User`:
#    - extends `AddressMixin`
#    - have appropriate factories


import logging

from itou.users.factories import JobSeekerFactory, JobSeekerWithAddressFactory


def test_simple_address():
    assert not JobSeekerWithAddressFactory().address_in_qpv
    assert not JobSeekerWithAddressFactory().zrr_city_name


def test_address_in_qpv():
    job_seeker = JobSeekerWithAddressFactory(with_address_in_qpv=True)

    assert job_seeker.address_on_one_line == job_seeker.address_in_qpv


def test_city_in_zrr():
    job_seeker = JobSeekerWithAddressFactory(with_city_in_zrr=True)
    city_name, partially_in_zrr = job_seeker.zrr_city_name

    assert city_name == job_seeker.city
    assert not partially_in_zrr


def test_city_partially_in_zrr():
    job_seeker = JobSeekerWithAddressFactory(with_city_partially_in_zrr=True)
    city_name, partially_in_zrr = job_seeker.zrr_city_name

    assert city_name == job_seeker.city
    assert partially_in_zrr


def test_zrr_warnings(caplog):
    caplog.set_level(logging.WARNING)
    job_seeker = JobSeekerWithAddressFactory()
    job_seeker.zrr_city_name

    assert "Can't match INSEE code" in caplog.text


def test_qpv_warnings(caplog):
    job_seeker = JobSeekerFactory()
    job_seeker.address_in_qpv

    assert "Unable to detect QPV" in caplog.text
