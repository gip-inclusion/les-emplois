import io
import textwrap

import factory
import pytest
from django import urls
from django.core import management
from django.utils import timezone
from faker import Faker
from pytest_django.asserts import assertContains

from itou.status import models, probes
from itou.status.management.commands import run_status_probes
from tests.status import factories


fake = Faker()


class SuccessProbe:
    name = "test.success"

    def check(self):
        return True, "OK"


class FailureProbe:
    name = "test.fail"

    def check(self):
        return False, "KO"


class ExceptionProbe:
    name = "test.exception"

    def check(self):
        raise Exception("Error")


class TestProbeStatusModel:
    def test_is_success_with_neither_success_or_failure(self):
        status = factories.ProbeStatusFactory()

        assert status.last_success_at is None
        assert status.last_failure_at is None
        assert status.is_success() is None

    def test_is_success_with_success(self):
        status = factories.ProbeStatusFactory(with_success=True)

        assert status.last_success_at is not None
        assert status.last_failure_at is None
        assert status.is_success() is True

    def test_is_success_with_failure(self):
        status = factories.ProbeStatusFactory(with_failure=True)

        assert status.last_success_at is None
        assert status.last_failure_at is not None
        assert status.is_success() is False

    def test_is_success_with_success_after_failure(self):
        status = factories.ProbeStatusFactory(
            with_success=True,
            with_failure=True,
            last_success_at=factory.Faker("future_datetime", tzinfo=timezone.get_default_timezone()),
        )

        assert status.last_success_at is not None
        assert status.last_failure_at is not None
        assert status.is_success() is True

    def test_is_success_with_success_before_failure(self):
        status = factories.ProbeStatusFactory(
            with_success=True,
            with_failure=True,
            last_failure_at=factory.Faker("future_datetime", tzinfo=timezone.get_default_timezone()),
        )

        assert status.last_success_at is not None
        assert status.last_failure_at is not None
        assert status.is_success() is False

    def test_is_success_with_success_and_failure_at_the_same_time(self):
        status = factories.ProbeStatusFactory(
            with_success=True, with_failure=True, last_failure_at=factory.SelfAttribute("last_success_at")
        )

        assert status.last_success_at is not None
        assert status.last_failure_at is not None
        assert status.last_success_at == status.last_failure_at
        assert status.is_success() is False


class TestRunStatusProbesCommand:
    @pytest.fixture()
    def cmd(self):
        return run_status_probes.Command(stdout=io.StringIO(), stderr=io.StringIO())

    def test_calling_by_name(self, mocker):
        mocker.patch("itou.status.probes.get_probes_classes", return_value=[])
        stdout = io.StringIO()

        management.call_command("run_status_probes", stdout=stdout, stderr=io.StringIO())
        assert stdout.getvalue() == textwrap.dedent(
            """\
                Start probing
                Check dangling probes
                No dangling probes found
                Running probes
                Finished probing
                """
        )

    def test_run_probes_when_probe_is_successful(self, subtests, cmd):
        for reason in ["Create", "Update"]:
            with subtests.test(reason):
                cmd._run_probes([SuccessProbe])

                status = models.ProbeStatus.objects.get(name=SuccessProbe.name)
                assert status.last_success_at is not None
                assert status.last_success_info == "OK"
                assert status.last_failure_at is None
                assert status.last_failure_info is None

    def test_run_probes_when_probe_fail(self, subtests, cmd):
        for reason in ["Create", "Update"]:
            with subtests.test(reason):
                cmd._run_probes([FailureProbe])

                status = models.ProbeStatus.objects.get(name=FailureProbe.name)
                assert status.last_failure_at is not None
                assert status.last_failure_info == "KO"
                assert status.last_success_at is None
                assert status.last_success_info is None

    def test_run_probes_when_probe_raise_an_exception(self, caplog, cmd):
        cmd._run_probes([ExceptionProbe])

        status = models.ProbeStatus.objects.get(name=ExceptionProbe.name)
        assert status.last_failure_at is not None
        assert status.last_failure_info == "Error"
        assert status.last_success_at is None
        assert status.last_success_info is None

        assert caplog.records[0].message == f"Probe {ExceptionProbe.name!r} failed"
        assert caplog.records[0].exc_info[0] is Exception

    def test_run_probes_when_everything_is_empty(self, cmd):
        assert models.ProbeStatus.objects.count() == 0

        cmd._run_probes([])

        assert models.ProbeStatus.objects.count() == 0

    def test_run_probes_when_adding_probes(self, cmd):
        factories.ProbeStatusFactory.create_batch(4)

        assert models.ProbeStatus.objects.count() == 4

        cmd._run_probes([SuccessProbe])

        assert models.ProbeStatus.objects.count() == 5

    def test_run_probes_when_removing_probes(self, cmd):
        factories.ProbeStatusFactory(name=SuccessProbe.name)
        factories.ProbeStatusFactory.create_batch(4)

        assert models.ProbeStatus.objects.count() == 5

        cmd._run_probes([SuccessProbe])

        assert models.ProbeStatus.objects.count() == 5

    def test_check_and_remove_dangling_probes_when_everything_is_empty(self, cmd):
        assert models.ProbeStatus.objects.count() == 0

        cmd._check_and_remove_dangling_probes([])

        assert models.ProbeStatus.objects.count() == 0
        assert cmd.stdout.getvalue() == "Check dangling probes\nNo dangling probes found\n"

    def test_check_and_remove_dangling_probes_with_existing_probes(self, cmd):
        non_dangling_probes = factories.ProbeStatusFactory.create_batch(3)

        cmd._check_and_remove_dangling_probes(non_dangling_probes)

        assert set(models.ProbeStatus.objects.values_list("name", flat=True)) == {
            probe.name for probe in non_dangling_probes
        }
        assert cmd.stdout.getvalue() == "Check dangling probes\nNo dangling probes found\n"

    def test_check_and_remove_dangling_probes_when_adding_probes(self, cmd):
        old_probes = factories.ProbeStatusFactory.create_batch(3)
        new_probes = factories.ProbeStatusFactory.build_batch(2)

        cmd._check_and_remove_dangling_probes(old_probes + new_probes)

        assert set(models.ProbeStatus.objects.values_list("name", flat=True)) == {probe.name for probe in old_probes}
        assert cmd.stdout.getvalue() == "Check dangling probes\nNo dangling probes found\n"

    def test_check_and_remove_dangling_probes_when_removing_probes(self, cmd):
        all_probes = factories.ProbeStatusFactory.create_batch(5)
        probes_kept, probes_removed = all_probes[:3], all_probes[3:]

        cmd._check_and_remove_dangling_probes(probes_kept)

        assert set(models.ProbeStatus.objects.values_list("name", flat=True)) == {probe.name for probe in probes_kept}
        expected_dangling_names = set(sorted({probe.name for probe in probes_removed}))
        assert cmd.stdout.getvalue() == f"Check dangling probes\nRemoving dangling probes: {expected_dangling_names}\n"

    def test_check_and_remove_dangling_probes_when_replacing_all_probes(self, cmd):
        old_probes = factories.ProbeStatusFactory.create_batch(3)
        new_probes = factories.ProbeStatusFactory.build_batch(2)

        cmd._check_and_remove_dangling_probes(new_probes)

        assert models.ProbeStatus.objects.count() == 0
        expected_dangling_names = set(sorted({probe.name for probe in old_probes}))
        assert cmd.stdout.getvalue() == f"Check dangling probes\nRemoving dangling probes: {expected_dangling_names}\n"


class TestViews:
    def test_index_show_all_probes(self, client):
        active_probes = probes.get_probes_classes()
        factories.ProbeStatusFactory(name="api.ban", with_success=True)
        factories.ProbeStatusFactory(name="api.geo", with_failure=True)

        response = client.get(urls.reverse("status:index"))
        assertContains(response, "<tr class=", count=len(active_probes))
        assertContains(response, "<td>OK</td>", count=1, html=True)
        assertContains(response, "<td>KO</td>", count=1, html=True)
        assertContains(response, "<td>???</td>", count=len(active_probes) - 2, html=True)

        for probe in active_probes:
            assertContains(response, f"<td>{probe.verbose_name}</td>", count=1, html=True)
