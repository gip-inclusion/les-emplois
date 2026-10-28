from rest_framework import serializers


class MailboxSerializer(serializers.Serializer):
    Name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    Address = serializers.EmailField()


class AttachmentSerializer(serializers.Serializer):
    Name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    ContentType = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    ContentLength = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    ContentID = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    DownloadToken = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class RecipientField(serializers.Field):
    def to_internal_value(self, data):
        if isinstance(data, str):
            return serializers.EmailField().run_validation(data)
        return MailboxSerializer().run_validation(data)

    def to_representation(self, value):
        return value


class EmailItemSerializer(serializers.Serializer):
    Uuid = serializers.ListField(required=False, child=serializers.CharField(), allow_empty=True, allow_null=True)
    MessageId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    InReplyTo = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    From = MailboxSerializer()
    To = MailboxSerializer(many=True)
    Recipients = serializers.ListField(child=RecipientField(), required=False, allow_empty=True)
    Cc = MailboxSerializer(many=True, required=False, allow_empty=True)
    ReplyTo = MailboxSerializer(required=False, allow_null=True)

    # This value is the one sent by the MTA. Therefore accept anything, we will parse it later and fallback on now().
    SentAtDate = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    Subject = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    RawHtmlBody = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    RawTextBody = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    ExtractedMarkdownMessage = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    ExtractedMarkdownSignature = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    SpamScore = serializers.FloatField(required=False, allow_null=True)

    Attachments = AttachmentSerializer(many=True, required=False, allow_empty=True)

    Headers = serializers.JSONField(required=False, default=dict)


class EmailsPayloadSerializer(serializers.Serializer):
    """
    From the Brevo documentation: https://developers.brevo.com/docs/inbound-parse-webhooks#parsed-email-payload
    The serializer validation is rather soft as we don’t want to refuse emails because of eg. a bad date formatting.
    """

    items = EmailItemSerializer(many=True)
