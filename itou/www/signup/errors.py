from collections import namedtuple

from django.contrib import messages
from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from itou.openid_connect.errors import format_error_modal_content
from itou.users.enums import IdentityProvider
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.emails import redact_email_address
from itou.utils.templatetags.str_filters import mask_unless


ConflictFields = namedtuple("ConflictFields", ["email", "nir", "first_name", "last_name", "birthdate"])


class JobSeekerSignupConflictModalResolver:
    """
    For improved accessibility in a context where users will often share emails and may have existing
    accounts at the time of signup, we support a range of specialized error messages to guide the user
    in finding their account in the event of a conflict.

    This class abstracts away the comparison of fields and modal rendering involved, to allow for a single-line
    provision of the feature, e.g.

    JobSeekerSignupConflictModalResolver(*args).evaluate(request)
    """

    existing_user: User = None
    fields: ConflictFields = None
    nir_submitted: bool = False

    def __init__(self, form_data, nir, email):
        email_conflict = User.objects.filter(email=email).first() if email is not None else None
        self.nir_submitted = nir is not None
        nir_conflict = User.objects.filter(jobseeker_profile__nir=nir).first() if self.nir_submitted else None

        # Check if there is a conflict - if the below condition is met, there's nothing to be done
        if not email_conflict and not nir_conflict:
            return

        # prioritise NIR conflict over email - more reliable source of identity
        self.existing_user = nir_conflict if nir_conflict else email_conflict

        # evalaute which fields are conflicting
        def compare_name(name_key):
            return (
                name_key in form_data and form_data[name_key].lower() == getattr(self.existing_user, name_key).lower()
            )

        self.fields = ConflictFields(
            email=(not nir_conflict or email_conflict == nir_conflict),
            nir=(nir_conflict is not None),
            first_name=compare_name("first_name"),
            last_name=compare_name("last_name"),
            birthdate=(
                "birthdate" in form_data and form_data["birthdate"] == self.existing_user.jobseeker_profile.birthdate
            ),
        )

    def evaluate(self, request):
        """Chooses a modal to send if indeed one should be sent"""

        # Check if there is a conflict - if the below condition is met, there's nothing to be done
        if not self.existing_user:
            return

        fields = self.fields
        count_fields = len(fields)
        count_matching = fields.count(True)
        count_not_matching = count_fields - count_matching

        # NOTE: ordered by priority (for greedy selection)
        modal_rules = [
            (self.modal_complete_match, lambda: not count_not_matching),
            (self.modal_off_by_one_field_match, lambda: fields.email and count_not_matching == 1),
            (self.modal_complete_match_without_email, lambda: not fields.email and count_not_matching == 1),
            (self.modal_nir_only, lambda: fields.nir and not fields.email),
            (self.modal_email_only, lambda: fields.email),
        ]
        for modal_func, conditions in modal_rules:
            if conditions():
                modal_func(request)
                break

    # Modals for the different variations of conflicting fields
    def _send_error_modal(self, request, html_content):
        messages.error(
            request,
            format_error_modal_content(
                html_content,
                reverse("login:existing_user", args=(self.existing_user.public_id,)),
                "Je me connecte avec ce compte",
            ),
            extra_tags="modal registration_failure",
        )

    def modal_email_only(self, request):
        self._send_error_modal(
            request,
            format_html(
                '<p class="h2">Un compte existe déjà avec cette adresse mail</p>'
                "<p><strong>Un compte au nom de {} a déjà été enregistré avec cette adresse e-mail.</strong></p>"
                "<ul><li>Si ce compte est bien le votre, connectez-vous en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong></li>'
                '<li>Si le compte n’est pas le votre, cliquez sur <strong>"Retour"</strong> '
                "et utilisez une autre adresse e-mail.</li></ul>",
                mask_unless(self.existing_user.get_full_name(), False),
            ),
        )

    def modal_nir_only(self, request):
        self._send_error_modal(
            request,
            format_html(
                '<p class="h2">Un compte existe déjà avec ce NIR</p>'
                "<p><strong>Un compte au nom de {} a déjà été enregistré avec ce NIR.</strong></p>"
                "<ul><li>Si ce compte est bien le votre, connectez-vous en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong></li>'
                '<li>Si ce NIR est bien le votre mais que ce n’est pas votre compte veuillez contacter"'
                "<a href={}>notre support</a>.</li></ul>",
                mask_unless(self.existing_user.get_full_name(), False),
                global_constants.ITOU_HELP_CENTER_URL,
            ),
        )

    def modal_complete_match(self, request):
        self._send_error_modal(
            request,
            mark_safe(
                '<p class="h2">Vous possédez déjà un compte</p>'
                "<p><strong>Un compte avec ses informations existe déjà.</strong></p>"
                "<p>Vous pouvez vous connecter directement en cliquant sur le bouton "
                '<strong>"Je me connecte avec ce compte".</strong></p>'
            ),
        )

    def modal_off_by_one_field_match(self, request):
        erroneous_field = [ConflictFields._fields[i] for i, x in enumerate(self.fields) if not x][0]
        try:
            field_name = User._meta.get_field(erroneous_field).verbose_name
        except FieldDoesNotExist:
            field_name = JobSeekerProfile._meta.get_field(erroneous_field).verbose_name
        self._send_error_modal(
            request,
            format_html(
                '<p class="h2">Un compte existe déjà avec un.e {} différent.e</p>'
                "<p><strong>Un compte similaire a déjà été enregistré.</strong></p>"
                "Si ce compte est bien le votre, vous pouvez vous connecter en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong>',
                field_name,
            ),
        )

    def modal_complete_match_without_email(self, request):
        reinitialize_pass_option = ""
        if self.existing_user.identity_provider == IdentityProvider.DJANGO:
            # TODO: test that the link does trigger an email
            reinitialize_pass_option = format_html(
                "<li>Si vous avez oublié votre mot de passe, un email vous sera envoyé en cliquant sur "
                "<a href={}>Réinitialiser mon mot de passe</a>.</li>",
                reverse("account_reset_password"),
            )
        self._send_error_modal(
            request,
            format_html(
                '<p class="h2">Un compte existe déjà avec une adresse e-mail différente</p>'
                "<p><strong>Un compte est déjà enregistré avec l'adresse e-mail {}.</strong></p>"
                "<ul><li>Si cette adresse mail est bien la votre, connectez-vous avec celle-ci en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong></li>{}<li>Si cette adresse mail '
                "n’est pas la votre veuillez contacter <a href={}>notre support</a>.</li></ul>",
                redact_email_address(self.existing_user.email),
                reinitialize_pass_option,
                global_constants.ITOU_HELP_CENTER_URL,
            ),
        )
