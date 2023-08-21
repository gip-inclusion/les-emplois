from django.core.management import call_command


def test_spectacular():
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", "/dev/null")
