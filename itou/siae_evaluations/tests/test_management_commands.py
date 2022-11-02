import datetime

from dateutil.relativedelta import relativedelta
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time

from .. import enums as evaluation_enums
from ..factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)


class TestManagementCommand:
    def test_no_campaign(self, capsys, mailoutbox):
        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert stdout == ""
        assert stderr == ""
        assert mailoutbox == []

    def test_no_notification_for_new_campaigns(self, capsys, mailoutbox):
        EvaluationCampaignFactory()
        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert stdout == ""
        assert stderr == ""
        assert mailoutbox == []

    def test_no_notification_for_closed_campaigns(self, capsys, mailoutbox):
        EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(days=30),
            ended_at=timezone.now(),
        )
        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert stdout == ""
        assert stderr == ""
        assert mailoutbox == []

    @freeze_time("2022-12-07 11:11:11")
    def test_notifies_all_campaigns(self, capsys, mailoutbox):
        campaign1 = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(days=30),
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
            institution__name="DDETS 01",
            name="Campagne 1",
        )
        evaluated_siae1 = EvaluatedSiaeFactory.create(
            evaluation_campaign=campaign1,
            siae__name="les petits jardins",
            siae__convention__siret_signature="00000000000032",
        )
        campaign2 = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(days=30),
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
            institution__name="DDETS 02",
            name="Campagne 1",
        )
        evaluated_siae2 = EvaluatedSiaeFactory.create(
            evaluation_campaign=campaign2,
            siae__name="Bazar antique",
            siae__convention__siret_signature="12345678900012",
        )
        evaluated_siae3 = EvaluatedSiaeFactory.create(
            evaluation_campaign=campaign2, siae__name="Trucs muche", siae__convention__siret_signature="12345678900024"
        )
        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert sorted(stdout.splitlines()) == [
            "Emailed reminders to 1 SIAE which did not submit proofs to DDETS 01 - Campagne 1.",
            "Emailed reminders to 2 SIAE which did not submit proofs to DDETS 02 - Campagne 1.",
        ]
        assert stderr == ""
        # EvaluatedSiae are not ordered.
        [mail1, mail2, mail3] = sorted(mailoutbox, key=lambda mail: (mail.subject, mail.body))
        assert mail1.subject == (
            "Contrôle a posteriori des auto-prescriptions : "
            "Plus que quelques jours pour transmettre vos justificatifs à la DDETS 01"
        )
        assert (
            f"Nous vous rappelons que votre structure EI les petits jardins ID-{evaluated_siae1.siae_id} "
            "(SIRET : 00000000000032) est soumise à la procédure de contrôle a posteriori sur les embauches réalisées "
            "en auto-prescription du 1 janvier 2022 au 30 septembre 2022.\n\n"
            "Vous devrez fournir les justificatifs des critères administratifs d’éligibilité IAE que vous aviez "
            "enregistrés lors de ces embauches.\n"
            "Nous vous rappelons que ce contrôle des DDETS doit être réalisé dans un délai de 6 semaines à compter du "
            "7 novembre 2022.\n\n" in mail1.body
        )
        assert f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae1.pk}/" in mail1.body
        assert mail2.subject == (
            "Contrôle a posteriori des auto-prescriptions : "
            "Plus que quelques jours pour transmettre vos justificatifs à la DDETS 02"
        )
        assert (
            f"Nous vous rappelons que votre structure EI Bazar antique ID-{evaluated_siae2.siae_id} "
            "(SIRET : 12345678900012) est soumise à la procédure de contrôle a posteriori sur les embauches réalisées "
            "en auto-prescription du 1 janvier 2022 au 30 septembre 2022.\n\n"
            "Vous devrez fournir les justificatifs des critères administratifs d’éligibilité IAE que vous aviez "
            "enregistrés lors de ces embauches.\n"
            "Nous vous rappelons que ce contrôle des DDETS doit être réalisé dans un délai de 6 semaines à compter du "
            "7 novembre 2022.\n\n" in mail2.body
        )
        assert f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae2.pk}/" in mail2.body
        assert mail3.subject == (
            "Contrôle a posteriori des auto-prescriptions : "
            "Plus que quelques jours pour transmettre vos justificatifs à la DDETS 02"
        )
        assert (
            f"Nous vous rappelons que votre structure EI Trucs muche ID-{evaluated_siae3.siae_id} "
            "(SIRET : 12345678900024) est soumise à la procédure de contrôle a posteriori sur les embauches réalisées "
            "en auto-prescription du 1 janvier 2022 au 30 septembre 2022.\n\n"
            "Vous devrez fournir les justificatifs des critères administratifs d’éligibilité IAE que vous aviez "
            "enregistrés lors de ces embauches.\n"
            "Nous vous rappelons que ce contrôle des DDETS doit être réalisé dans un délai de 6 semaines à compter du "
            "7 novembre 2022.\n\n" in mail3.body
        )
        assert f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae3.pk}/" in mail3.body

    @freeze_time("2022-12-07 11:11:11")
    def test_notify_fallback(self, capsys, mailoutbox):
        "Crons did not run at D+30, the system should catch up."
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(days=31),
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
            institution__name="DDETS 01",
            name="Campagne 1",
        )
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign=campaign,
            siae__name="les petits jardins",
            siae__convention__siret_signature="00000000000032",
        )
        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert stdout.splitlines() == [
            "Emailed reminders to 1 SIAE which did not submit proofs to DDETS 01 - Campagne 1."
        ]
        assert stderr == ""
        [mail] = mailoutbox
        assert mail.subject == (
            "Contrôle a posteriori des auto-prescriptions : "
            "Plus que quelques jours pour transmettre vos justificatifs à la DDETS 01"
        )
        assert (
            f"Nous vous rappelons que votre structure EI les petits jardins ID-{evaluated_siae.siae_id} "
            "(SIRET : 00000000000032) est soumise à la procédure de contrôle a posteriori sur les embauches réalisées "
            "en auto-prescription du 1 janvier 2022 au 30 septembre 2022.\n\n"
            "Vous devrez fournir les justificatifs des critères administratifs d’éligibilité IAE que vous aviez "
            "enregistrés lors de ces embauches.\n"
            "Nous vous rappelons que ce contrôle des DDETS doit être réalisé dans un délai de 6 semaines à compter du "
            "6 novembre 2022.\n\n" in mail.body
        )
        assert f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae.pk}/" in mail.body

    @freeze_time("2022-12-07 11:11:11")
    def test_does_not_notify_twice(self, capsys, mailoutbox):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(days=31),
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
            institution__name="DDETS 01",
            name="Campagne 1",
        )
        EvaluatedSiaeFactory.create(
            evaluation_campaign=campaign,
            siae__name="les petits jardins",
            siae__convention__siret_signature="00000000000032",
            reminder_sent_at=timezone.now() - relativedelta(days=1),
        )
        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert stdout == ""
        assert stderr == ""
        assert mailoutbox == []

    @freeze_time("2022-12-07 11:11:11")
    def test_no_notification(self, capsys, mailoutbox):
        campaign = EvaluationCampaignFactory(evaluations_asked_at=timezone.now() - relativedelta(days=30))
        evaluated_job_app_submitted = EvaluatedJobApplicationFactory(evaluated_siae__evaluation_campaign=campaign)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app_submitted,
            uploaded_at=timezone.now() - relativedelta(days=3),
            submitted_at=timezone.now() - relativedelta(days=2),
        )

        evaluated_job_app_accepted = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign=campaign,
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=1),
            evaluated_siae__final_reviewed_at=timezone.now() - relativedelta(days=1),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app_accepted,
            uploaded_at=timezone.now() - relativedelta(days=3),
            submitted_at=timezone.now() - relativedelta(days=2),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )

        evaluated_job_app_refused = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign=campaign,
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=1),
            evaluated_siae__final_reviewed_at=timezone.now() - relativedelta(days=1),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app_refused,
            uploaded_at=timezone.now() - relativedelta(days=3),
            submitted_at=timezone.now() - relativedelta(days=2),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )

        evaluated_job_app_adversarial = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign=campaign,
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=1),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app_adversarial,
            uploaded_at=timezone.now() - relativedelta(days=3),
            submitted_at=timezone.now() - relativedelta(days=2),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )

        # Aversarial, no proof.
        EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign=campaign,
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=1),
        )

        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert stdout == ""
        assert stderr == ""
        assert mailoutbox == []

    @freeze_time("2022-12-07 11:11:11")
    def test_notification_for_siaes_without_proofs(self, capsys, mailoutbox):
        campaign = EvaluationCampaignFactory(
            evaluations_asked_at=timezone.now() - relativedelta(days=30),
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 9, 30),
            institution__name="DDETS 01",
            name="Campagne de test",
        )

        evaluated_siae_no_proof = EvaluatedSiaeFactory.create(
            evaluation_campaign=campaign,
            siae__name="les petits jardins",
            siae__convention__siret_signature="00000000000032",
        )
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_no_proof)

        evaluated_siae_not_submitted = EvaluatedSiaeFactory.create(
            evaluation_campaign=campaign,
            siae__name="trier pour la planète",
            siae__convention__siret_signature="12345678900012",
        )
        evaluated_job_app_not_submitted = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae_not_submitted)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app_not_submitted,
            uploaded_at=timezone.now() - relativedelta(days=3),
        )

        call_command("evaluation_campaign_notify")
        stdout, stderr = capsys.readouterr()
        assert stdout == "Emailed reminders to 2 SIAE which did not submit proofs to DDETS 01 - Campagne de test.\n"
        assert stderr == ""
        mail1, mail2 = mailoutbox
        if mail1.body > mail2.body:
            # EvaluatedSiae are not ordered, email order is not deterministic.
            mail2, mail1 = mail1, mail2
        assert mail1.subject == (
            "Contrôle a posteriori des auto-prescriptions : "
            "Plus que quelques jours pour transmettre vos justificatifs à la DDETS 01"
        )
        assert (
            f"Nous vous rappelons que votre structure EI les petits jardins ID-{evaluated_siae_no_proof.siae_id} "
            "(SIRET : 00000000000032) est soumise à la procédure de contrôle a posteriori sur les embauches réalisées "
            "en auto-prescription du 1 janvier 2022 au 30 septembre 2022.\n\n"
            "Vous devrez fournir les justificatifs des critères administratifs d’éligibilité IAE que vous aviez "
            "enregistrés lors de ces embauches.\n"
            "Nous vous rappelons que ce contrôle des DDETS doit être réalisé dans un délai de 6 semaines à compter du "
            "7 novembre 2022.\n\n" in mail1.body
        )
        assert (
            f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae_no_proof.pk}/"
            in mail1.body
        )
        assert mail2.subject == (
            "Contrôle a posteriori des auto-prescriptions : "
            "Plus que quelques jours pour transmettre vos justificatifs à la DDETS 01"
        )
        assert (
            "Nous vous rappelons que votre structure EI trier pour la planète ID-"
            f"{evaluated_siae_not_submitted.siae_id} (SIRET : 12345678900012) est soumise à la procédure de contrôle "
            "a posteriori sur les embauches réalisées en auto-prescription du 1 janvier 2022 au 30 septembre 2022.\n\n"
            "Vous devrez fournir les justificatifs des critères administratifs d’éligibilité IAE que vous aviez "
            "enregistrés lors de ces embauches.\n"
            "Nous vous rappelons que ce contrôle des DDETS doit être réalisé dans un délai de 6 semaines à compter du "
            "7 novembre 2022.\n\n" in mail2.body
        )
        assert (
            f"http://127.0.0.1:8000/siae_evaluation/siae_job_applications_list/{evaluated_siae_not_submitted.pk}/"
            in mail2.body
        )
