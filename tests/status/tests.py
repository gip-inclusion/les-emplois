import io
import textwrap
from unittest import mock

import factory
import pytest
from django import urls
from django.core import management
from django.utils import timezone
from faker import Faker

from itou.status import models, probes
from itou.status.management.commands import run_status_probes
from tests.status import factories
from tests.utils.test import TestCase


pytestmark = pytest.mark.ignore_template_errors

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


class ProbeStatusModelTest(TestCase):
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


class RunStatusProbesCommandTest(TestCase):
    def setUp(self):
        super().setUp()
        self.cmd = run_status_probes.Command(stdout=io.StringIO(), stderr=io.StringIO())

    @mock.patch("itou.status.probes.get_probes_classes", mock.Mock(return_value=[]))
    def test_calling_by_name(self):
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

    def test_run_probes_when_probe_is_successful(self):
        for reason in ["Create", "Update"]:
            with self.subTest(reason):
                self.cmd._run_probes([SuccessProbe])

                status = models.ProbeStatus.objects.get(name=SuccessProbe.name)
                assert status.last_success_at is not None
                assert status.last_success_info == "OK"
                assert status.last_failure_at is None
                assert status.last_failure_info is None

    def test_run_probes_when_probe_fail(self):
        for reason in ["Create", "Update"]:
            with self.subTest(reason):
                self.cmd._run_probes([FailureProbe])

                status = models.ProbeStatus.objects.get(name=FailureProbe.name)
                assert status.last_failure_at is not None
                assert status.last_failure_info == "KO"
                assert status.last_success_at is None
                assert status.last_success_info is None

    def test_run_probes_when_probe_raise_an_exception(self):
        with self.assertLogs() as cm:
            self.cmd._run_probes([ExceptionProbe])

        status = models.ProbeStatus.objects.get(name=ExceptionProbe.name)
        assert status.last_failure_at is not None
        assert status.last_failure_info == "Error"
        assert status.last_success_at is None
        assert status.last_success_info is None

        assert cm.records[0].message == f"Probe {ExceptionProbe.name!r} failed"
        assert cm.records[0].exc_info[0] is Exception

    def test_run_probes_when_everything_is_empty(self):
        assert models.ProbeStatus.objects.count() == 0

        self.cmd._run_probes([])

        assert models.ProbeStatus.objects.count() == 0

    def test_run_probes_when_adding_probes(self):
        factories.ProbeStatusFactory.create_batch(4)

        assert models.ProbeStatus.objects.count() == 4

        self.cmd._run_probes([SuccessProbe])

        assert models.ProbeStatus.objects.count() == 5

    def test_run_probes_when_removing_probes(self):
        factories.ProbeStatusFactory(name=SuccessProbe.name)
        factories.ProbeStatusFactory.create_batch(4)

        assert models.ProbeStatus.objects.count() == 5

        self.cmd._run_probes([SuccessProbe])

        assert models.ProbeStatus.objects.count() == 5

    def test_check_and_remove_dangling_probes_when_everything_is_empty(self):
        assert models.ProbeStatus.objects.count() == 0

        self.cmd._check_and_remove_dangling_probes([])

        assert models.ProbeStatus.objects.count() == 0
        assert self.cmd.stdout.getvalue() == "Check dangling probes\nNo dangling probes found\n"

    def test_check_and_remove_dangling_probes_with_existing_probes(self):
        non_dangling_probes = factories.ProbeStatusFactory.create_batch(3)

        self.cmd._check_and_remove_dangling_probes(non_dangling_probes)

        assert set(models.ProbeStatus.objects.values_list("name", flat=True)) == {
            probe.name for probe in non_dangling_probes
        }
        assert self.cmd.stdout.getvalue() == "Check dangling probes\nNo dangling probes found\n"

    def test_check_and_remove_dangling_probes_when_adding_probes(self):
        old_probes = factories.ProbeStatusFactory.create_batch(3)
        new_probes = factories.ProbeStatusFactory.build_batch(2)

        self.cmd._check_and_remove_dangling_probes(old_probes + new_probes)

        assert set(models.ProbeStatus.objects.values_list("name", flat=True)) == {probe.name for probe in old_probes}
        assert self.cmd.stdout.getvalue() == "Check dangling probes\nNo dangling probes found\n"

    def test_check_and_remove_dangling_probes_when_removing_probes(self):
        all_probes = factories.ProbeStatusFactory.create_batch(5)
        probes_kept, probes_removed = all_probes[:3], all_probes[3:]

        self.cmd._check_and_remove_dangling_probes(probes_kept)

        assert set(models.ProbeStatus.objects.values_list("name", flat=True)) == {probe.name for probe in probes_kept}
        expected_dangling_names = set(sorted({probe.name for probe in probes_removed}))
        assert (
            self.cmd.stdout.getvalue()
            == f"Check dangling probes\nRemoving dangling probes: {expected_dangling_names}\n"
        )

    def test_check_and_remove_dangling_probes_when_replacing_all_probes(self):
        old_probes = factories.ProbeStatusFactory.create_batch(3)
        new_probes = factories.ProbeStatusFactory.build_batch(2)

        self.cmd._check_and_remove_dangling_probes(new_probes)

        assert models.ProbeStatus.objects.count() == 0
        expected_dangling_names = set(sorted({probe.name for probe in old_probes}))
        assert (
            self.cmd.stdout.getvalue()
            == f"Check dangling probes\nRemoving dangling probes: {expected_dangling_names}\n"
        )


class ViewsTest(TestCase):
    def test_index_show_all_probes(self):
        active_probes = probes.get_probes_classes()
        factories.ProbeStatusFactory(name="api.ban", with_success=True)
        factories.ProbeStatusFactory(name="api.geo", with_failure=True)

        response = self.client.get(urls.reverse("status:index"))
        self.assertContains(response, "<tr class=", count=len(active_probes))
        self.assertContains(response, "<td>OK</td>", count=1, html=True)
        self.assertContains(response, "<td>KO</td>", count=1, html=True)
        self.assertContains(response, "<td>???</td>", count=len(active_probes) - 2, html=True)

        for probe in active_probes:
            self.assertContains(response, f"<td>{probe.verbose_name}</td>", count=1, html=True)
