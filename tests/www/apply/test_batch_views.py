import uuid

from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertMessages, assertRedirects

from itou.job_applications.enums import JobApplicationState
from itou.utils.urls import add_url_params
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
)
from tests.users.factories import (
    LaborInspectorFactory,
)


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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "REFUSED"})
        client.force_login(employer)

        archivable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.REFUSED)

        response = client.post(
            add_url_params(reverse("apply:batch_archive"), {"next_url": next_url}),
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

        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "REFUSED"})

        response = client.post(
            add_url_params(reverse("apply:batch_archive"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "REFUSED"})

        client.force_login(archivable_app.sender)
        response = client.post(
            add_url_params(reverse("apply:batch_archive"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "REFUSED"})
        client.force_login(employer)

        response = client.post(
            add_url_params(reverse("apply:batch_archive"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "NEW"})
        client.force_login(employer)

        unarchivable_app = JobApplicationFactory(
            job_seeker__first_name="John",
            job_seeker__last_name="Rambo",
            to_company=company,
            state=JobApplicationState.NEW,
        )
        assert unarchivable_app.archived_at is None

        response = client.post(
            add_url_params(reverse("apply:batch_archive"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "REFUSED"})
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
            add_url_params(reverse("apply:batch_archive"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"start_date": "1970-01-01"})

        response = client.post(
            add_url_params(reverse("apply:batch_archive"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "PROCESSING"})
        client.force_login(employer)

        postponable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING)

        response = client.post(
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
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

        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "PROCESSING"})

        response = client.post(
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "PROCESSING"})
        client.force_login(postponable_app.sender)
        response = client.post(
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "PROCESSING"})
        client.force_login(employer)

        response = client.post(
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "PROCESSING"})
        client.force_login(employer)

        postponable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING, answer="")

        response = client.post(
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
            data={"answer": "", "application_ids": [postponable_app.pk]},
        )
        assertRedirects(response, next_url)
        postponable_app.refresh_from_db()
        assert postponable_app.state != JobApplicationState.POSTPONED
        assert not postponable_app.answer
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR, "Les candidatures n’ont pas pu être mises en attente.", extra_tags="toast"
                )
            ],
        )

    def test_unpostponable(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "PROCESSING"})
        client.force_login(employer)

        unpostponable_app = JobApplicationFactory(
            job_seeker__first_name="John",
            job_seeker__last_name="Rambo",
            to_company=company,
            state=JobApplicationState.NEW,
        )
        assert not unpostponable_app.postpone.is_available()

        response = client.post(
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "PROCESSING"})
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
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"start_date": "1970-01-01"})

        response = client.post(
            add_url_params(reverse("apply:batch_postpone"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "NEW"})
        client.force_login(employer)

        transferable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)

        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
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

        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "REFUSED"})

        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "NEW"})
        assert transferable_app.transfer.is_available()

        client.force_login(transferable_app.sender)
        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "NEW"})
        client.force_login(employer)

        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "ACCEPTED"})
        client.force_login(employer)

        untransferable_app = JobApplicationFactory(
            job_seeker__first_name="John",
            job_seeker__last_name="Rambo",
            to_company=company,
            state=JobApplicationState.ACCEPTED,
        )
        assert not untransferable_app.transfer.is_available()

        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
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

    def test_already_transfered(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        other_company = CompanyMembershipFactory(user=employer).company
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "NEW"})
        client.force_login(employer)

        transferable_app = JobApplicationFactory(to_company=other_company, state=JobApplicationState.NEW)

        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
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
        next_url = add_url_params(reverse("apply:list_for_siae"), {"state": "NEW"})
        client.force_login(employer)

        transferable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)

        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
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
            # 1 already transfered application:
            JobApplicationFactory(
                job_seeker__first_name="Jean",
                job_seeker__last_name="Bond",
                to_company=other_company,
                state=JobApplicationState.NEW,
                archived_at=timezone.now(),
            ),
        ]

        next_url = add_url_params(reverse("apply:list_for_siae"), {"start_date": "1970-01-01"})

        response = client.post(
            add_url_params(reverse("apply:batch_transfer"), {"next_url": next_url}),
            data={
                "target_company_id": other_company.pk,
                "application_ids": ([transferable_app.pk for transferable_app in apps] + [uuid.uuid4(), uuid.uuid4()]),
            },
        )
        assertRedirects(response, next_url)
        # 2 transferable apps have been successfully transfered despite all the error messages
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
