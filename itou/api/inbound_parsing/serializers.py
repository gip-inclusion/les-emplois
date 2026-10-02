from rest_framework import serializers


class MailboxSerializer(serializers.Serializer):
    Name = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    Address = serializers.EmailField()


class AttachmentSerializer(serializers.Serializer):
    Name = serializers.CharField()
    ContentType = serializers.CharField()
    ContentLength = serializers.IntegerField(min_value=0)
    ContentID = serializers.CharField()
    DownloadToken = serializers.CharField()


class EmailItemSerializer(serializers.Serializer):
    Uuid = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    MessageId = serializers.CharField()
    InReplyTo = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    From = MailboxSerializer()
    To = MailboxSerializer(many=True)
    Recipients = serializers.ListField(child=serializers.EmailField(), required=False, allow_empty=True)
    Cc = MailboxSerializer(many=True, required=False, allow_empty=True)
    ReplyTo = MailboxSerializer(required=False, allow_null=True)

    SentAtDate = serializers.DateTimeField(input_formats=["%a, %d %b %Y %H:%M:%S %z"])

    Subject = serializers.CharField(allow_blank=True, allow_null=True)
    RawHtmlBody = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    RawTextBody = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    ExtractedMarkdownMessage = serializers.CharField(allow_blank=True, allow_null=True)
    ExtractedMarkdownSignature = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    SpamScore = serializers.FloatField(required=False, allow_null=True)

    Attachments = AttachmentSerializer(many=True, required=False, allow_empty=True)

    Headers = serializers.JSONField(required=False, default=dict)


class EmailsPayloadSerializer(serializers.Serializer):
    """
    From the Brevo documentation: https://developers.brevo.com/docs/inbound-parse-webhooks#parsed-email-payload
    """

    items = EmailItemSerializer(many=True)
