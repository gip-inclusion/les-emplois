from urllib.parse import urlencode

from django.urls import reverse
from django.utils.html import escape
from httpx import Response
from pytest_django.asserts import assertContains, assertNotContains

from itou.emails.models import Email
from itou.utils.urls import add_url_params


class TestEmailAdmin:
    def test_view_email_success(self, admin_client, success_response):
        email = Email.objects.create(
            to=["you@test.local"],
            cc=[],
            bcc=[],
            subject="Hi",
            body_text="Hello",
            esp_response=success_response,
        )
        response = admin_client.get(reverse("admin:emails_email_change", kwargs={"object_id": email.pk}))
        [message] = success_response["Messages"]
        [status] = message["To"]
        mailjet_url = reverse("admin:emails_email_mailjet", args=(status["MessageID"],))
        assertContains(
            response,
            f"""
            <h3>To</h3>
            <ul class="inline">
                <li><a href="{mailjet_url}">you@test.local</a></li>
            </ul>
            """,
            html=True,
            count=1,
        )

    def test_view_email_error(self, admin_client, error_response):
        email = Email.objects.create(
            to=["you@test.local"],
            cc=[],
            bcc=[],
            subject="Hi",
            body_text="Hello",
            esp_response=error_response,
        )
        response = admin_client.get(reverse("admin:emails_email_change", kwargs={"object_id": email.pk}))
        assertContains(
            response,
            # JSON is escaped.
            "<pre><code>[{&#x27;ErrorCode&#x27;: &#x27;send-0003&#x27;,\n"
            "  &#x27;ErrorIdentifier&#x27;: &#x27;88b5ca9f-5f1f-42e7-a45e-9ecbad0c285e&#x27;,\n"
            "  &#x27;ErrorMessage&#x27;: &#x27;At least &quot;HTMLPart&quot;, &quot;TextPart&quot; "
            "or &quot;TemplateID&quot; must be provided.&#x27;,\n"
            "  &#x27;ErrorRelatedTo&#x27;: [&#x27;HTMLPart&#x27;, &#x27;TextPart&#x27;],\n"
            "  &#x27;StatusCode&#x27;: 400}]</code></pre>",
            count=1,
        )

    def test_filter_changelist_on_status(self, admin_client, error_response, success_response):
        waiting_email = Email(
            to=["you@test.local"],
            cc=[],
            bcc=[],
            subject="Hi",
            body_text="Hello",
            # No esp_response.
        )
        error_email = Email(
            to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello", esp_response=error_response
        )
        success_email = Email(
            to=["you@test.local"],
            cc=[],
            bcc=[],
            subject="Hi",
            body_text="Hello",
            esp_response=success_response,
        )
        Email.objects.bulk_create([waiting_email, error_email, success_email])
        search_errors = {"sent_to_esp": "0"}
        response = admin_client.get(reverse("admin:emails_email_changelist"), search_errors)
        errors_urlencoded = urlencode(search_errors)
        search_success = {"sent_to_esp": "1"}
        success_urlencoded = urlencode(search_success)
        waiting_email_url = escape(
            add_url_params(
                reverse("admin:emails_email_change", kwargs={"object_id": waiting_email.pk}),
                {"_changelist_filters": errors_urlencoded},
            )
        )
        error_email_url = escape(
            add_url_params(
                reverse("admin:emails_email_change", kwargs={"object_id": error_email.pk}),
                {"_changelist_filters": errors_urlencoded},
            )
        )
        success_email_url = escape(
            add_url_params(
                reverse("admin:emails_email_change", kwargs={"object_id": success_email.pk}),
                {"_changelist_filters": success_urlencoded},
            )
        )

        def email_th(email_url):
            return f'<th class="field-to"><a href="{email_url}">you@test.local</a></th>'

        assertContains(
            response, '<span class="small quiet">2 résultats (<a href="?">Tout afficher</a>)</span>', count=1
        )
        assertContains(response, email_th(waiting_email_url), count=1)
        assertContains(response, email_th(error_email_url), count=1)
        assertNotContains(response, success_email_url)

        response = admin_client.get(reverse("admin:emails_email_changelist"), search_success)
        assertContains(
            response, '<span class="small quiet">1 résultat (<a href="?">Tout afficher</a>)</span>', count=1
        )
        assertNotContains(response, waiting_email_url)
        assertNotContains(response, error_email_url)
        assertContains(response, email_th(success_email_url), count=1)

    def test_view_mailjet_response(self, admin_client, respx_mock, mailjet_messagehistory_response, settings):
        settings.ANYMAIL["MAILJET_API_KEY"] = "key"
        settings.ANYMAIL["MAILJET_SECRET_KEY"] = "secret"
        message_id = 2345
        respx_mock.get(url=f"https://api.mailjet.com/v3/REST/messagehistory/{message_id}").mock(
            return_value=Response(
                status_code=200,
                json=mailjet_messagehistory_response,
            )
        )
        response = admin_client.get(reverse("admin:emails_email_mailjet", args=(message_id,)))
        assert response.json() == mailjet_messagehistory_response
