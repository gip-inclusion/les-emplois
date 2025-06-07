import random
import uuid

from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertMessages, assertRedirects

from itou.job_applications import enums as job_applications_enums
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.www.apply.views.batch_views import RefuseWizardView
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
)
from tests.users.factories import (
    JobSeekerFactory,
    LaborInspectorFactory,
)
from tests.utils.test import get_session_name


class TestBatchArchive:
    def test_invalid_access(self, client):
        archivable_app = JobApplicationFactory(state=JobApplicationState.REFUSED)
        assert archivable_app.can_be_archived
        for user in [archivable_app.job_seeker, archivable_app.sender, LaborInspectorFactory(membership=True)]:
            client.force_login(user)
            response = client.post(reverse("apply:batch_archive"), data={"application_ids": [archivable_app.pk]})
            assert response.status_code == 403

    def test_no_next_url(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        archivable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.REFUSED)

        response = client.post(reverse("apply:batch_archive"), data={"application_ids": [archivable_app.pk]})
        assert response.status_code == 404

    def test_single_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "REFUSED"})
        client.force_login(employer)

        archivable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.REFUSED)

        response = client.post(
            reverse("apply:batch_archive", query={"next_url": next_url}),
            data={"application_ids": [archivable_app.pk]},
        )
        assertRedirects(response, next_url)
        archivable_app.refresh_from_db()
        assert archivable_app.archived_at is not None
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "1 candidature a bien été archivée.", extra_tags="toast")],
        )

    def test_multiple_apps(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        archivable_apps = JobApplicationFactory.create_batch(2, to_company=company, state=JobApplicationState.REFUSED)

        next_url = reverse("apply:list_for_siae", query={"state": "REFUSED"})

        response = client.post(
            reverse("apply:batch_archive", query={"next_url": next_url}),
            data={"application_ids": [archivable_app.pk for archivable_app in archivable_apps]},
        )
        assertRedirects(response, next_url)
        for archivable_app in archivable_apps:
            archivable_app.refresh_from_db()
            assert archivable_app.archived_at is not None
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "2 candidatures ont bien été archivées.", extra_tags="toast")],
        )

    def test_sent_application(self, client):
        archivable_app = JobApplicationFactory(sent_by_another_employer=True, state=JobApplicationState.REFUSED)
        assert archivable_app.can_be_archived
        next_url = reverse("apply:list_for_siae", query={"state": "REFUSED"})

        client.force_login(archivable_app.sender)
        response = client.post(
            reverse("apply:batch_archive", query={"next_url": next_url}),
            data={"application_ids": [archivable_app.pk]},
        )
        assertRedirects(response, next_url)
        archivable_app.refresh_from_db()
        assert archivable_app.archived_at is None
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_unexisting_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "REFUSED"})
        client.force_login(employer)

        response = client.post(
            reverse("apply:batch_archive", query={"next_url": next_url}),
            data={"application_ids": [uuid.uuid4()]},
        )
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_unarchivable(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        unarchivable_app = JobApplicationFactory(
            job_seeker__first_name="John",
            job_seeker__last_name="Rambo",
            to_company=company,
            state=JobApplicationState.NEW,
        )
        assert unarchivable_app.archived_at is None

        response = client.post(
            reverse("apply:batch_archive", query={"next_url": next_url}),
            data={"application_ids": [unarchivable_app.pk]},
        )
        assertRedirects(response, next_url)
        unarchivable_app.refresh_from_db()
        assert unarchivable_app.archived_at is None
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de John RAMBO n’a pas pu être archivée car elle est au statut "
                        "« Nouvelle candidature »."
                    ),
                    extra_tags="toast",
                ),
            ],
        )

    def test_already_archived(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "REFUSED"})
        client.force_login(employer)

        archived_app = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="Bond",
            to_company=company,
            state=JobApplicationState.REFUSED,
            archived_at=timezone.now(),
        )
        assert archived_app.archived_at is not None

        response = client.post(
            reverse("apply:batch_archive", query={"next_url": next_url}),
            data={"application_ids": [archived_app.pk]},
        )
        assertRedirects(response, next_url)
        archived_app.refresh_from_db()
        assert archived_app.archived_at is not None
        assertMessages(
            response,
            [
                messages.Message(
                    messages.WARNING,
                    "La candidature de Jean BOND est déjà archivée.",
                    extra_tags="toast",
                ),
            ],
        )

    def test_mishmash(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        apps = [
            # 2 archivable applications:
            JobApplicationFactory(to_company=company, state=JobApplicationState.CANCELLED),
            JobApplicationFactory(to_company=company, state=JobApplicationState.REFUSED),
            # 1 unarchivable application:
            JobApplicationFactory(
                job_seeker__first_name="John",
                job_seeker__last_name="Rambo",
                to_company=company,
                state=JobApplicationState.NEW,
            ),
            # 1 already archived application:
            JobApplicationFactory(
                job_seeker__first_name="Jean",
                job_seeker__last_name="Bond",
                to_company=company,
                state=JobApplicationState.REFUSED,
                archived_at=timezone.now(),
            ),
        ]
        next_url = reverse("apply:list_for_siae", query={"start_date": "1970-01-01"})

        response = client.post(
            reverse("apply:batch_archive", query={"next_url": next_url}),
            data={"application_ids": [app.pk for app in apps] + [uuid.uuid4(), uuid.uuid4()]},
        )
        assertRedirects(response, next_url)
        # 2 archivable apps have been successfully archived despite all the error messages
        apps[0].refresh_from_db()
        assert apps[0].archived_at is not None
        apps[1].refresh_from_db()
        assert apps[1].archived_at is not None
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "2 candidatures sélectionnées n’existent plus ou ont été transférées.",
                ),
                messages.Message(
                    messages.WARNING,
                    "La candidature de Jean BOND est déjà archivée.",
                    extra_tags="toast",
                ),
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de John RAMBO n’a pas pu être archivée car elle est au statut "
                        "« Nouvelle candidature »."
                    ),
                    extra_tags="toast",
                ),
                messages.Message(messages.SUCCESS, "2 candidatures ont bien été archivées.", extra_tags="toast"),
            ],
        )


class TestBatchPostpone:
    FAKE_ANSWER = "Lorem ipsum postponed"

    def test_invalid_access(self, client):
        postponable_app = JobApplicationFactory(state=JobApplicationState.PROCESSING)
        assert postponable_app.postpone.is_available()
        for user in [postponable_app.job_seeker, postponable_app.sender, LaborInspectorFactory(membership=True)]:
            client.force_login(user)
            response = client.post(
                reverse("apply:batch_postpone"),
                data={"answer": self.FAKE_ANSWER, "application_ids": [postponable_app.pk]},
            )
            assert response.status_code == 403

    def test_no_next_url(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        postponable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING)
        assert postponable_app.postpone.is_available()

        response = client.post(
            reverse("apply:batch_postpone"), data={"answer": self.FAKE_ANSWER, "application_ids": [postponable_app.pk]}
        )
        assert response.status_code == 404

    def test_single_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(employer)

        postponable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING)

        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={
                "answer": self.FAKE_ANSWER,
                "application_ids": [postponable_app.pk],
            },
        )
        assertRedirects(response, next_url)
        postponable_app.refresh_from_db()
        assert postponable_app.state == JobApplicationState.POSTPONED
        assert postponable_app.answer == self.FAKE_ANSWER
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "La candidature a bien été mise en attente.", extra_tags="toast")],
        )

    def test_multiple_apps(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        postponable_apps = JobApplicationFactory.create_batch(
            2, to_company=company, state=JobApplicationState.PROCESSING
        )

        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})

        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={
                "answer": self.FAKE_ANSWER,
                "application_ids": [postponable_app.pk for postponable_app in postponable_apps],
            },
        )
        # Check that next_url parameter is honored
        assertRedirects(response, next_url)
        for postponable_app in postponable_apps:
            postponable_app.refresh_from_db()
            assert postponable_app.state == JobApplicationState.POSTPONED
            assert postponable_app.answer == self.FAKE_ANSWER
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "2 candidatures ont bien été mises en attente.", extra_tags="toast")],
        )

    def test_sent_application(self, client):
        postponable_app = JobApplicationFactory(sent_by_another_employer=True, state=JobApplicationState.PROCESSING)
        assert postponable_app.postpone.is_available()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(postponable_app.sender)
        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={"answer": self.FAKE_ANSWER, "application_ids": [postponable_app.pk]},
        )
        assertRedirects(response, next_url)
        postponable_app.refresh_from_db()
        assert postponable_app.state == JobApplicationState.PROCESSING
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_unexisting_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(employer)

        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={"answer": self.FAKE_ANSWER, "application_ids": [uuid.uuid4()]},
        )
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_missing_answer(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(employer)

        postponable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING, answer="")

        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={"answer": "", "application_ids": [postponable_app.pk]},
        )
        assertRedirects(response, next_url)
        postponable_app.refresh_from_db()
        assert postponable_app.state == JobApplicationState.POSTPONED
        assert postponable_app.answer == ""
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "La candidature a bien été mise en attente.", extra_tags="toast")],
        )

    def test_unpostponable(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(employer)

        unpostponable_app = JobApplicationFactory(
            job_seeker__first_name="John",
            job_seeker__last_name="Rambo",
            to_company=company,
            state=JobApplicationState.NEW,
        )
        assert not unpostponable_app.postpone.is_available()

        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={"answer": self.FAKE_ANSWER, "application_ids": [unpostponable_app.pk]},
        )
        assertRedirects(response, next_url)
        unpostponable_app.refresh_from_db()
        assert unpostponable_app.state == JobApplicationState.NEW
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de John RAMBO n’a pas pu être mise en attente car elle est au statut "
                        "« Nouvelle candidature »."
                    ),
                    extra_tags="toast",
                ),
            ],
        )

    def test_already_postponed(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(employer)

        postponed_app = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="Bond",
            to_company=company,
            state=JobApplicationState.POSTPONED,
            answer="An existing answer",
            archived_at=timezone.now(),
        )
        assert not postponed_app.postpone.is_available()

        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={"answer": self.FAKE_ANSWER, "application_ids": [postponed_app.pk]},
        )
        assertRedirects(response, next_url)
        postponed_app.refresh_from_db()
        assert postponed_app.state == JobApplicationState.POSTPONED
        assert postponed_app.answer != self.FAKE_ANSWER
        assertMessages(
            response,
            [
                messages.Message(
                    messages.WARNING,
                    "La candidature de Jean BOND est déjà mise en attente.",
                    extra_tags="toast",
                ),
            ],
        )

    def test_mishmash(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        apps = [
            # 2 archivable applications:
            JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING),
            JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING),
            # 1 unarchivable application:
            JobApplicationFactory(
                job_seeker__first_name="John",
                job_seeker__last_name="Rambo",
                to_company=company,
                state=JobApplicationState.NEW,
            ),
            # 1 already postponed application:
            JobApplicationFactory(
                job_seeker__first_name="Jean",
                job_seeker__last_name="Bond",
                to_company=company,
                state=JobApplicationState.POSTPONED,
                archived_at=timezone.now(),
            ),
        ]
        next_url = reverse("apply:list_for_siae", query={"start_date": "1970-01-01"})

        response = client.post(
            reverse("apply:batch_postpone", query={"next_url": next_url}),
            data={
                "answer": self.FAKE_ANSWER,
                "application_ids": [app.pk for app in apps] + [uuid.uuid4(), uuid.uuid4()],
            },
        )
        # Check that next_url parameter is honored
        assertRedirects(response, next_url)
        # 2 postponable apps have been successfully archived despite all the error messages
        apps[0].refresh_from_db()
        assert apps[0].state == JobApplicationState.POSTPONED
        assert apps[0].answer == self.FAKE_ANSWER
        apps[1].refresh_from_db()
        assert apps[1].state == JobApplicationState.POSTPONED
        assert apps[1].answer == self.FAKE_ANSWER
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "2 candidatures sélectionnées n’existent plus ou ont été transférées.",
                ),
                messages.Message(
                    messages.WARNING,
                    "La candidature de Jean BOND est déjà mise en attente.",
                    extra_tags="toast",
                ),
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de John RAMBO n’a pas pu être mise en attente car elle est au statut "
                        "« Nouvelle candidature »."
                    ),
                    extra_tags="toast",
                ),
                messages.Message(
                    messages.SUCCESS, "2 candidatures ont bien été mises en attente.", extra_tags="toast"
                ),
            ],
        )


class TestBatchRefuse:
    FAKE_JOB_SEEKER_ANSWER = "Lorem ipsum candidatum"
    FAKE_PRESCRIBER_ANSWER = "Lorem ipsum prescribum"

    def test_invalid_access(self, client):
        refusable_app = JobApplicationFactory(state=JobApplicationState.NEW)
        assert refusable_app.refuse.is_available()
        for user in [refusable_app.job_seeker, refusable_app.sender, LaborInspectorFactory(membership=True)]:
            client.force_login(user)
            response = client.post(
                reverse("apply:batch_refuse"),
                data={"application_ids": [refusable_app.pk]},
            )
            assert response.status_code == 403

    def test_no_next_url(self, client):
        refusable_app = JobApplicationFactory(sent_by_another_employer=True, state=JobApplicationState.NEW)
        assert refusable_app.refuse.is_available()

        client.force_login(refusable_app.sender)
        response = client.post(reverse("apply:batch_refuse"), data={"application_ids": [refusable_app.pk]})
        assert response.status_code == 404

    def test_sent_application(self, client):
        refusable_app = JobApplicationFactory(sent_by_another_employer=True, state=JobApplicationState.NEW)
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        assert refusable_app.refuse.is_available()

        client.force_login(refusable_app.sender)
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [refusable_app.pk]},
        )
        assertRedirects(response, next_url)
        refusable_app.refresh_from_db()
        assert refusable_app.state == JobApplicationState.NEW
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_unexisting_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [uuid.uuid4()]},
        )
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_unrefusable_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        unrefusable_app = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="BOND",
            to_company=company,
            state=JobApplicationState.ACCEPTED,
        )
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [unrefusable_app.pk]},
        )
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de Jean BOND ne peut pas être refusée car elle est au statut "
                        "« Candidature acceptée »."
                    ),
                    extra_tags="toast",
                ),
            ],
        )

    def test_single_app_from_orienter(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        refusable_app = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="BOND",
            to_company=company,
            state=JobApplicationState.PROCESSING,
        )

        # Start view
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [refusable_app.pk]},
        )
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        expected_session = {
            "config": {
                "tunnel": "batch",
                "reset_url": next_url,
            },
            "application_ids": [refusable_app.pk],
        }
        assert client.session[refuse_session_name] == expected_session
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        # Check redirect
        assertRedirects(response, refusal_reason_url, fetch_redirect_response=False)

        # Reason step
        response = client.get(refusal_reason_url)
        assertContains(response, "<strong>Étape 1</strong>/3 : Choix du motif de refus", html=True)
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-reason-submit"

        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": True,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        expected_session["reason"] = post_data
        assert client.session[refuse_session_name] == expected_session
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        assertRedirects(response, job_seeker_answer_url)

        # Job seeker answer step
        assertContains(response, "<strong>Étape 2</strong>/3 : Message au candidat", html=True)
        assertContains(response, "Réponse au candidat")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-job-seeker-answer-submit"
        post_data = {"job_seeker_answer": self.FAKE_JOB_SEEKER_ANSWER}
        response = client.post(job_seeker_answer_url, data=post_data, follow=True)
        expected_session["job-seeker-answer"] = post_data
        assert client.session[refuse_session_name] == expected_session
        prescriber_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "prescriber-answer"}
        )
        assertRedirects(response, prescriber_answer_url)

        # Prescriber answer step
        assertContains(response, "<strong>Étape 3</strong>/3 : Message à l’orienteur", html=True)
        assertContains(response, "Réponse à l’orienteur")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-prescriber-answer-submit"
        post_data = {"prescriber_answer": self.FAKE_PRESCRIBER_ANSWER}
        response = client.post(prescriber_answer_url, data=post_data, follow=True)
        assertRedirects(response, next_url)
        # Session has been cleaned
        assert refuse_session_name not in client.session
        refusable_app.refresh_from_db()
        assert refusable_app.state == JobApplicationState.REFUSED
        assert refusable_app.answer == self.FAKE_JOB_SEEKER_ANSWER
        assert refusable_app.answer_to_prescriber == self.FAKE_PRESCRIBER_ANSWER
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS, "La candidature de Jean BOND a bien été refusée.", extra_tags="toast"
                )
            ],
        )

    def test_multiple_apps_from_authorized_prescribers(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        refusable_apps = [
            JobApplicationFactory(
                to_company=company,
                state=JobApplicationState.PROCESSING,
                sent_by_authorized_prescriber_organisation=True,
            ),
            JobApplicationFactory(
                to_company=company,
                state=JobApplicationState.PROCESSING,
                sent_by_authorized_prescriber_organisation=True,
            ),
        ]

        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})

        # Start view
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [refusable_app.pk for refusable_app in refusable_apps]},
        )
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        expected_session = {
            "config": {
                "tunnel": "batch",
                "reset_url": next_url,
            },
            "application_ids": [refusable_apps[1].pk, refusable_apps[0].pk],  # default application ordering
        }
        assert client.session[refuse_session_name] == expected_session
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        # Check redirect
        assertRedirects(response, refusal_reason_url, fetch_redirect_response=False)

        # Reason step
        response = client.get(refusal_reason_url)
        assertContains(response, "<strong>Étape 1</strong>/3 : Choix du motif de refus", html=True)
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-reason-submit"

        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": True,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        expected_session["reason"] = post_data
        assert client.session[refuse_session_name] == expected_session
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        assertRedirects(response, job_seeker_answer_url)

        # Job seeker answer step
        assertContains(response, "<strong>Étape 2</strong>/3 : Message aux candidats", html=True)
        assertContains(response, "Réponse aux candidats")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-job-seeker-answer-submit"
        post_data = {"job_seeker_answer": self.FAKE_JOB_SEEKER_ANSWER}
        response = client.post(job_seeker_answer_url, data=post_data, follow=True)
        expected_session["job-seeker-answer"] = post_data
        assert client.session[refuse_session_name] == expected_session
        prescriber_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "prescriber-answer"}
        )
        assertRedirects(response, prescriber_answer_url)

        # Prescriber answer step
        assertContains(response, "<strong>Étape 3</strong>/3 : Message aux prescripteurs", html=True)
        assertContains(response, "Réponse aux prescripteurs")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-prescriber-answer-submit"
        post_data = {"prescriber_answer": self.FAKE_PRESCRIBER_ANSWER}
        response = client.post(prescriber_answer_url, data=post_data, follow=True)
        assertRedirects(response, next_url)
        # Session has been cleaned
        assert refuse_session_name not in client.session
        for refusable_app in refusable_apps:
            refusable_app.refresh_from_db()
            assert refusable_app.state == JobApplicationState.REFUSED
            assert refusable_app.answer == self.FAKE_JOB_SEEKER_ANSWER
            assert refusable_app.answer_to_prescriber == self.FAKE_PRESCRIBER_ANSWER
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "2 candidatures ont bien été refusées.", extra_tags="toast")],
        )

    def test_multiple_apps_from_same_job_seeker(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        job_seeker = JobSeekerFactory()
        refusable_apps = JobApplicationFactory.create_batch(
            2,
            to_company=company,
            state=JobApplicationState.PROCESSING,
            job_seeker=job_seeker,
            sender=job_seeker,
            sender_kind=SenderKind.JOB_SEEKER,
        )

        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})

        # Start view
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [refusable_app.pk for refusable_app in refusable_apps]},
        )
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        expected_session = {
            "config": {
                "tunnel": "batch",
                "reset_url": next_url,
            },
            "application_ids": [refusable_apps[1].pk, refusable_apps[0].pk],  # default application ordering
        }
        assert client.session[refuse_session_name] == expected_session
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        # Check redirect
        assertRedirects(response, refusal_reason_url, fetch_redirect_response=False)

        # Reason step
        response = client.get(refusal_reason_url)
        assertContains(response, "<strong>Étape 1</strong>/2 : Choix du motif de refus", html=True)
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-reason-submit"

        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": False,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        expected_session["reason"] = post_data
        assert client.session[refuse_session_name] == expected_session
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        assertRedirects(response, job_seeker_answer_url)

        # Job seeker answer step
        assertContains(response, "<strong>Étape 2</strong>/2 : Message au candidat", html=True)
        assertContains(response, "Réponse au candidat")
        assertContains(
            response,
            f"<strong>Motif de refus :</strong> {reason_label} <em>(Motif non communiqué au candidat)</em>",
            html=True,
        )
        assert response.context["matomo_custom_title"] == "Candidatures refusées"
        assert response.context["matomo_event_name"] == "batch-refuse-applications-job-seeker-answer-submit"
        post_data = {"job_seeker_answer": self.FAKE_JOB_SEEKER_ANSWER}
        response = client.post(job_seeker_answer_url, data=post_data, follow=True)
        assertRedirects(response, next_url)
        # Session has been cleaned
        assert refuse_session_name not in client.session
        for refusable_app in refusable_apps:
            refusable_app.refresh_from_db()
            assert refusable_app.state == JobApplicationState.REFUSED
            assert refusable_app.answer == self.FAKE_JOB_SEEKER_ANSWER
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "2 candidatures ont bien été refusées.", extra_tags="toast")],
        )

    def test_refuse_step_bypass(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(employer)

        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        refusable_app = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="BOND",
            to_company=company,
            state=JobApplicationState.PROCESSING,
        )

        # Start view
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [refusable_app.pk]},
        )
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        expected_session = {
            "config": {
                "tunnel": "batch",
                "reset_url": next_url,
            },
            "application_ids": [refusable_app.pk],
        }
        assert client.session[refuse_session_name] == expected_session
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        prescriber_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "prescriber-answer"}
        )
        # Check redirect
        assertRedirects(response, refusal_reason_url, fetch_redirect_response=False)

        # Direct access to following steps redirect to 1st one
        for step_url in [job_seeker_answer_url, prescriber_answer_url]:
            response = client.get(step_url)
            assertRedirects(response, refusal_reason_url, fetch_redirect_response=False)

        # Fill 1st step data
        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": False,
        }
        response = client.post(refusal_reason_url, data=post_data)
        expected_session["reason"] = post_data
        assert client.session[refuse_session_name] == expected_session

        # Step 3 redirects to unfilled step 2
        response = client.get(prescriber_answer_url)
        assertRedirects(response, job_seeker_answer_url, fetch_redirect_response=False)

    def test_single_app_transferred_concurrently(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})
        client.force_login(employer)

        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        refusable_app = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="BOND",
            to_company=company,
            state=JobApplicationState.PROCESSING,
        )

        # Start view
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [refusable_app.pk]},
        )
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        expected_session = {
            "config": {
                "tunnel": "batch",
                "reset_url": next_url,
            },
            "application_ids": [refusable_app.pk],
        }
        assert client.session[refuse_session_name] == expected_session
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        # Check redirect
        assertRedirects(response, refusal_reason_url, fetch_redirect_response=False)

        # Reason step
        response = client.get(refusal_reason_url)
        assertContains(response, "<strong>Étape 1</strong>/3 : Choix du motif de refus", html=True)

        refusable_app.to_company = CompanyFactory()
        refusable_app.save(update_fields=("to_company", "updated_at"))

        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": True,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        assert response.status_code == 404
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                    extra_tags="toast",
                )
            ],
        )

    def test_multiple_apps_deleted_concurrently(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        refusable_apps = [
            JobApplicationFactory(
                to_company=company,
                state=JobApplicationState.PROCESSING,
                sent_by_authorized_prescriber_organisation=True,
            ),
            JobApplicationFactory(
                job_seeker__first_name="Jean",
                job_seeker__last_name="BOND",
                to_company=company,
                state=JobApplicationState.PROCESSING,
                sent_by_authorized_prescriber_organisation=True,
            ),
        ]

        next_url = reverse("apply:list_for_siae", query={"state": "PROCESSING"})

        # Start view
        response = client.post(
            reverse("apply:batch_refuse", query={"next_url": next_url}),
            data={"application_ids": [refusable_app.pk for refusable_app in refusable_apps]},
        )
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        expected_session = {
            "config": {
                "tunnel": "batch",
                "reset_url": next_url,
            },
            "application_ids": [refusable_apps[1].pk, refusable_apps[0].pk],  # default application ordering
        }
        assert client.session[refuse_session_name] == expected_session
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        # Check redirect
        assertRedirects(response, refusal_reason_url, fetch_redirect_response=False)

        # Reason step
        response = client.get(refusal_reason_url)
        assertContains(response, "<strong>Étape 1</strong>/3 : Choix du motif de refus", html=True)

        # One of the application is removed (or transferred)
        refusable_apps[0].delete()

        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": True,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        expected_session["reason"] = post_data
        expected_session["application_ids"] = [refusable_apps[1].pk]  # refusable_apps[0].pk has been removed
        assert client.session[refuse_session_name] == expected_session
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        assertRedirects(response, job_seeker_answer_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                    extra_tags="toast",
                )
            ],
        )

        # Job seeker answer step
        assertContains(response, "<strong>Étape 2</strong>/3 : Message au candidat", html=True)
        assertContains(response, "Réponse au candidat")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        post_data = {"job_seeker_answer": self.FAKE_JOB_SEEKER_ANSWER}
        response = client.post(job_seeker_answer_url, data=post_data, follow=True)
        expected_session["job-seeker-answer"] = post_data
        assert client.session[refuse_session_name] == expected_session
        prescriber_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "prescriber-answer"}
        )
        assertRedirects(response, prescriber_answer_url)

        # Prescriber answer step
        assertContains(response, "<strong>Étape 3</strong>/3 : Message au prescripteur", html=True)
        assertContains(response, "Réponse au prescripteur")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        post_data = {"prescriber_answer": self.FAKE_PRESCRIBER_ANSWER}
        response = client.post(prescriber_answer_url, data=post_data, follow=True)
        assertRedirects(response, next_url)
        # Session has been cleaned
        assert refuse_session_name not in client.session
        refusable_apps[1].refresh_from_db()
        assert refusable_apps[1].state == JobApplicationState.REFUSED
        assert refusable_apps[1].answer == self.FAKE_JOB_SEEKER_ANSWER
        assert refusable_apps[1].answer_to_prescriber == self.FAKE_PRESCRIBER_ANSWER
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS, "La candidature de Jean BOND a bien été refusée.", extra_tags="toast"
                )
            ],
        )


class TestBatchTransfer:
    def test_invalid_access(self, client):
        transferable_app = JobApplicationFactory(state=JobApplicationState.NEW)
        company = CompanyFactory(with_membership=True)
        assert transferable_app.transfer.is_available()
        for user in [transferable_app.job_seeker, transferable_app.sender, LaborInspectorFactory(membership=True)]:
            client.force_login(user)
            response = client.post(
                reverse("apply:batch_transfer"),
                data={"target_company_id": company.pk, "application_ids": [transferable_app.pk]},
            )
            assert response.status_code == 403

    def test_no_next_url(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyMembershipFactory(user=employer).company
        client.force_login(employer)

        transferable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)

        response = client.post(
            reverse("apply:batch_transfer"),
            data={"target_company_id": other_company.pk, "application_ids": [transferable_app.pk]},
        )
        assert response.status_code == 404

    def test_single_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyMembershipFactory(user=employer).company
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        transferable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)

        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={"target_company_id": other_company.pk, "application_ids": [transferable_app.pk]},
        )
        assertRedirects(response, next_url)
        transferable_app.refresh_from_db()
        assert transferable_app.to_company == other_company
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "1 candidature a bien été transférée.", extra_tags="toast")],
        )

    def test_multiple_apps(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyMembershipFactory(user=employer).company
        client.force_login(employer)

        transferable_apps = JobApplicationFactory.create_batch(2, to_company=company, state=JobApplicationState.NEW)

        next_url = reverse("apply:list_for_siae", query={"state": "REFUSED"})

        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={
                "target_company_id": other_company.pk,
                "application_ids": [transferable_app.pk for transferable_app in transferable_apps],
            },
        )
        assertRedirects(response, next_url)
        for transferable_app in transferable_apps:
            transferable_app.refresh_from_db()
            assert transferable_app.to_company == other_company
        assertMessages(
            response,
            [messages.Message(messages.SUCCESS, "2 candidatures ont bien été transférées.", extra_tags="toast")],
        )

    def test_sent_application(self, client):
        transferable_app = JobApplicationFactory(sent_by_another_employer=True, state=JobApplicationState.NEW)
        to_company = transferable_app.to_company
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        assert transferable_app.transfer.is_available()

        client.force_login(transferable_app.sender)
        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={
                "target_company_id": transferable_app.sender_company.pk,
                "application_ids": [transferable_app.pk],
            },
        )
        assertRedirects(response, next_url)
        transferable_app.refresh_from_db()
        assert transferable_app.to_company == to_company
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_unexisting_app(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={
                "target_company_id": company.pk,
                "application_ids": [uuid.uuid4()],
            },
        )
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_untransferable(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyMembershipFactory(user=employer).company
        next_url = reverse("apply:list_for_siae", query={"state": "ACCEPTED"})
        client.force_login(employer)

        untransferable_app = JobApplicationFactory(
            job_seeker__first_name="John",
            job_seeker__last_name="Rambo",
            to_company=company,
            state=JobApplicationState.ACCEPTED,
        )
        assert not untransferable_app.transfer.is_available()

        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={"target_company_id": other_company.pk, "application_ids": [untransferable_app.pk]},
        )
        assertRedirects(response, next_url)
        untransferable_app.refresh_from_db()
        assert untransferable_app.to_company == company
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de John RAMBO n’a pas pu être transférée car elle est au statut "
                        "« Candidature acceptée »."
                    ),
                    extra_tags="toast",
                ),
            ],
        )

    def test_already_transferred(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyMembershipFactory(user=employer).company
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        transferable_app = JobApplicationFactory(to_company=other_company, state=JobApplicationState.NEW)

        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={"target_company_id": other_company.pk, "application_ids": [transferable_app.pk]},
        )
        assertRedirects(response, next_url)
        transferable_app.refresh_from_db()
        assert transferable_app.to_company == other_company
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Une candidature sélectionnée n’existe plus ou a été transférée.",
                ),
            ],
        )

    def test_wrong_company(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyFactory(with_membership=True)
        next_url = reverse("apply:list_for_siae", query={"state": "NEW"})
        client.force_login(employer)

        transferable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)

        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={"target_company_id": other_company.pk, "application_ids": [transferable_app.pk]},
        )
        assert response.status_code == 404

    def test_mishmash(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyMembershipFactory(user=employer).company
        client.force_login(employer)

        apps = [
            # 2 transferable applications:
            JobApplicationFactory(to_company=company, state=JobApplicationState.NEW),
            JobApplicationFactory(to_company=company, state=JobApplicationState.POSTPONED),
            # 1 untransferable application:
            JobApplicationFactory(
                job_seeker__first_name="John",
                job_seeker__last_name="Rambo",
                to_company=company,
                state=JobApplicationState.ACCEPTED,
            ),
            # 1 already transferred application:
            JobApplicationFactory(
                job_seeker__first_name="Jean",
                job_seeker__last_name="Bond",
                to_company=other_company,
                state=JobApplicationState.NEW,
                archived_at=timezone.now(),
            ),
        ]

        next_url = reverse("apply:list_for_siae", query={"start_date": "1970-01-01"})

        response = client.post(
            reverse("apply:batch_transfer", query={"next_url": next_url}),
            data={
                "target_company_id": other_company.pk,
                "application_ids": ([transferable_app.pk for transferable_app in apps] + [uuid.uuid4(), uuid.uuid4()]),
            },
        )
        assertRedirects(response, next_url)
        # 2 transferable apps have been successfully transferred despite all the error messages
        apps[0].refresh_from_db()
        assert apps[0].to_company == other_company
        apps[1].refresh_from_db()
        assert apps[1].to_company == other_company
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "3 candidatures sélectionnées n’existent plus ou ont été transférées.",
                ),
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de John RAMBO n’a pas pu être transférée car elle est au statut "
                        "« Candidature acceptée »."
                    ),
                    extra_tags="toast",
                ),
                messages.Message(messages.SUCCESS, "2 candidatures ont bien été transférées.", extra_tags="toast"),
            ],
        )
