from collections import namedtuple

from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from itou.openid_connect.errors import format_error_modal_content
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
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
    errors = None

    def __init__(self, cleaned_data, errors, nir, email):
        self.errors = errors
        job_seekers = User.objects.filter(kind=UserKind.JOB_SEEKER)
        email_conflict_user = job_seekers.filter(email=email).first() if email is not None else None
        nir_conflict_user = job_seekers.filter(nir=nir).first() if nir is not None else None

        # A guess of identity is made (in order of priority) on NIR, email, and birth details
        # The final fallback is included because users will sometimes create one account with a temporary NIR,
        # only to later re-subscribe later when they have a permanent one
        self.existing_user = (
            nir_conflict_user
            or email_conflict_user
            or (
                all(key in cleaned_data for key in ["birthdate", "first_name", "last_name"])
                and job_seekers.filter(
                    birthdate=cleaned_data["birthdate"],
                    first_name__unaccent__iexact=cleaned_data["first_name"],
                    last_name__unaccent__iexact=cleaned_data["last_name"],
                ).first()
            )
        )

        # If none of these fields are in conflict, there is nothing to be done by the modal resolver
        if not self.existing_user:
            return

        # evaluate which fields are conflicting
        def compare_name(name_key):
            return (
                name_key in cleaned_data
                and cleaned_data[name_key].lower() == getattr(self.existing_user, name_key).lower()
            )

        self.fields = ConflictFields(
            email=(email_conflict_user is not None),
            nir=(nir_conflict_user is not None),
            first_name=compare_name("first_name"),
            last_name=compare_name("last_name"),
            birthdate=(
                "birthdate" in cleaned_data
                and cleaned_data["birthdate"] == self.existing_user.jobseeker_profile.birthdate
            ),
        )

    def evaluate(self, request):
        """Chooses a modal to send if indeed one should be sent"""

        # Check if there is a conflict - if the below condition is met, there's nothing to be done
        if not self.existing_user:
            return

        fields = self.fields
        count_not_matching = fields.count(False)

        # NOTE: ordered by priority (for greedy selection)
        modal_rules = [
            (self.modal_complete_match, not count_not_matching),
            (
                self.modal_complete_match,
                count_not_matching == 1
                and (fields.email and not fields.nir and self.existing_user.jobseeker_profile.nir == ""),
            ),
            (self.modal_off_by_one_field_match, fields.email and count_not_matching == 1),
            (self.modal_email_only, fields.email),
            (self.modal_complete_match_without_email, not fields.email and count_not_matching == 1),
            (self.modal_nir_only, fields.nir and not fields.email),
            (self.modal_birth_fields, not fields.email and not fields.nir),
        ]
        for modal_func, conditions_met in modal_rules:
            if conditions_met:
                modal_func(request)
                break

    # Modals for the different variations of conflicting fields
    def _send_error_modal(self, request, html_content, modal_title_name, dismiss_text="Retour"):
        messages.error(
            request,
            format_error_modal_content(
                html_content,
                reverse("login:existing_user", args=(self.existing_user.public_id,)),
                "Je me connecte avec ce compte",
                dismiss_text,
            ),
            extra_tags=f"modal registration_failure {modal_title_name}",
        )

    def modal_email_only(self, request):
        self._send_error_modal(
            request,
            format_html(
                "<p><strong>Un compte au nom de {} a déjà été enregistré avec cette adresse e-mail.</strong></p>"
                "<ul><li>Si ce compte est bien le vôtre, connectez-vous en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong></li>'
                '<li>Si le compte n’est pas le vôtre, cliquez sur <strong>"Retour"</strong> '
                "et utilisez une autre adresse e-mail.</li></ul>",
                mask_unless(self.existing_user.get_full_name(), False),
            ),
            "email_conflict",
        )

    def modal_nir_only(self, request):
        self._send_error_modal(
            request,
            format_html(
                "<p><strong>Un compte au nom de {} a déjà été enregistré avec ce NIR.</strong></p>"
                "<ul><li>Si ce compte est bien le vôtre, connectez-vous en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong></li>'
                "<li>Si ce NIR est bien le vôtre mais que ce n’est pas votre compte veuillez contacter "
                '<a href="{}" target="_blank">notre support</a>.</li></ul>',
                mask_unless(self.existing_user.get_full_name(), False),
                f"{global_constants.ITOU_HELP_CENTER_URL}/requests/new",
            ),
            "nir_conflict",
        )

    def modal_complete_match(self, request):
        self._send_error_modal(
            request,
            mark_safe(
                "<p><strong>Un compte associé à ces informations existe déjà.</strong></p>"
                "<p>Vous pouvez vous connecter directement en cliquant sur le bouton "
                '<strong>"Je me connecte avec ce compte".</strong></p>'
            ),
            "user_exists",
        )

    def modal_off_by_one_field_match(self, request):
        erroneous_field = [ConflictFields._fields[i] for i, x in enumerate(self.fields) if not x][0]
        self._send_error_modal(
            request,
            mark_safe(
                "<p><strong>Un compte similaire a déjà été enregistré.</strong></p>"
                "Si ce compte est bien le vôtre, vous pouvez vous connecter en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong>',
            ),
            f"user_exists_without_{erroneous_field}",
        )

    def modal_complete_match_without_email(self, request):
        reinitialize_pass_option = ""
        if self.existing_user.identity_provider == IdentityProvider.DJANGO:
            reinitialize_pass_option = format_html(
                "<li>Si vous avez oublié votre mot de passe, veuillez cliquer sur "
                '<a href="{}">Réinitialiser mon mot de passe</a>.</li>',
                reverse("account_reset_password"),
            )
        self._send_error_modal(
            request,
            format_html(
                "<p><strong>Un compte est déjà enregistré avec l’adresse e-mail {}.</strong></p>"
                "<ul><li>Si cette adresse mail est bien la vôtre, connectez-vous avec celle-ci en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong></li>{}<li>Si cette adresse mail '
                'n’est pas la vôtre veuillez contacter <a href="{}" target="_blank">notre support</a>.</li></ul>',
                redact_email_address(self.existing_user.email),
                reinitialize_pass_option,
                f"{global_constants.ITOU_HELP_CENTER_URL}/requests/new",
            ),
            "user_exists_without_email",
        )

    def modal_birth_fields(self, request):
        """
        A weak match. Neither NIR or email involved, only name and birth date.
        In this case the user can continue if desired.
        """
        reinitialize_pass_option = ""
        if self.existing_user.identity_provider == IdentityProvider.DJANGO:
            reinitialize_pass_option = format_html(
                "<li>Si vous avez oublié votre mot de passe, veuillez cliquer sur "
                '<a href="{}">Réinitialiser mon mot de passe</a>.</li>',
                reverse("account_reset_password"),
            )
        self._send_error_modal(
            request,
            format_html(
                "<p><strong>Un compte est déjà enregistré avec l’adresse e-mail {}.</strong></p>"
                "<ul><li>Si cette adresse mail est bien la vôtre, connectez-vous avec celle-ci en cliquant sur "
                '<strong>"Je me connecte avec ce compte".</strong></li>{}<li>Si cette adresse mail '
                "n’est pas la vôtre vous pouvez <strong>continuez l’inscription</strong></li></ul>",
                redact_email_address(self.existing_user.email),
                reinitialize_pass_option,
            ),
            "user_exists_with_birth_fields",
            "Continuer l’inscription" if not self.errors else "Retour",
        )
