"""
Send notifications to Slack.

Thanks to
https://gist.github.com/devStepsize/b1b795309a217d24566dcc0ad136f784
"""
import json

import requests
from django.conf import settings


def send_slack_message(text="Hello world :wave:"):
    if not settings.SLACK_CRON_WEBHOOK_URL:
        return
    response = requests.post(
        url=settings.SLACK_CRON_WEBHOOK_URL,
        data=json.dumps({"text": text}),
        headers={"Content-Type": "application/json"},
    )
    if response.status_code != 200:
        raise ValueError(
            "Request to slack returned an error %s, the response is:\n%s" % (response.status_code, response.text)
        )
