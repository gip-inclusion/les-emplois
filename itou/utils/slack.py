"""
Send notifications to Slack.

Thanks to
https://gist.github.com/devStepsize/b1b795309a217d24566dcc0ad136f784
"""

import json

import httpx
from django.conf import settings


def send_slack_message(text="Hello world :wave:"):
    if not settings.SLACK_CRON_WEBHOOK_URL:
        return
    response = httpx.post(
        url=settings.SLACK_CRON_WEBHOOK_URL,
        data=json.dumps({"text": text}),
        headers={"Content-Type": "application/json"},
    )
    if response.status_code != 200:
        raise ValueError(
            f"Request to slack returned an error {response.status_code}, the response is:\n{response.text}"
        )
