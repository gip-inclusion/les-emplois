# Generated by Django 5.1.9 on 2025-06-06 12:30

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0008_alter_file_key_uniq"),
        ("antivirus", "0001_initial"),
        ("approvals", "0012_fix_prolongations_declared_by_jobseeker"),
        ("communications", "0005_fill_image_dimensions"),
        ("geiq_assessments", "0001_initial"),
        ("job_applications", "0017_jobapplication_job_seeker_sender_coherence"),
        ("siae_evaluations", "0003_delete_2021_test_campaigns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # Drop varchar_pattern_ops indexes
                migrations.RunSQL(
                    # The index name django automaticaly computes changed because of the column renaming
                    """
                    DROP INDEX IF EXISTS files_file_key_1c5dd06d_like;
                    DROP INDEX IF EXISTS antivirus_scan_file_id_48667630_like;
                    DROP INDEX IF EXISTS approvals_prolongation_report_file_id_3c95babf_like;
                    DROP INDEX IF EXISTS approvals_prolongationrequest_report_file_id_7200b042_like;
                    DROP INDEX IF EXISTS communications_announcementitem_image_storage_id_6ce5930b_like;
                    DROP INDEX IF EXISTS geiq_assessments_assessm_action_financial_assessm_8d3e6e9a_like;
                    DROP INDEX IF EXISTS geiq_assessments_assessm_structure_financial_asse_20ceb0b7_like;
                    DROP INDEX IF EXISTS geiq_assessments_assessm_summary_document_file_id_9c3ad4a0_like;
                    DROP INDEX IF EXISTS job_applications_jobapplication_resume_id_98d390bf_like;
                    DROP INDEX IF EXISTS siae_evaluations_evaluat_proof_id_d9c3e434_like;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # Drop all constrains on FK columns
                migrations.RunSQL(
                    """
                    ALTER TABLE antivirus_scan DROP CONSTRAINT antivirus_scan_file_id_48667630_fk_files_file_key;
                    ALTER TABLE approvals_prolongation DROP CONSTRAINT approvals_prolongati_report_file_id_3c95babf_fk_files_fil;
                    ALTER TABLE approvals_prolongationrequest DROP CONSTRAINT approvals_prolongati_report_file_id_7200b042_fk_files_fil;
                    ALTER TABLE communications_announcementitem DROP CONSTRAINT communications_annou_image_storage_id_6ce5930b_fk_files_fil;
                    ALTER TABLE geiq_assessments_assessment DROP CONSTRAINT geiq_assessments_ass_action_financial_ass_8d3e6e9a_fk_files_fil;
                    ALTER TABLE geiq_assessments_assessment DROP CONSTRAINT geiq_assessments_ass_structure_financial__20ceb0b7_fk_files_fil;
                    ALTER TABLE geiq_assessments_assessment DROP CONSTRAINT geiq_assessments_ass_summary_document_fil_9c3ad4a0_fk_files_fil;
                    ALTER TABLE job_applications_jobapplication DROP CONSTRAINT job_applications_job_resume_id_98d390bf_fk_files_fil;
                    ALTER TABLE siae_evaluations_evaluatedadministrativecriteria DROP CONSTRAINT siae_evaluations_eva_proof_id_d9c3e434_fk_files_fil;
                    """,  # noqa: E501
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # Update column type
                migrations.RunSQL(
                    """
                    ALTER TABLE files_file ALTER COLUMN id TYPE uuid USING id::uuid;
                    ALTER TABLE antivirus_scan ALTER COLUMN file_id TYPE uuid USING file_id::uuid;
                    ALTER TABLE approvals_prolongation ALTER COLUMN report_file_id TYPE uuid USING report_file_id::uuid;
                    ALTER TABLE approvals_prolongationrequest ALTER COLUMN report_file_id TYPE uuid USING report_file_id::uuid;
                    ALTER TABLE communications_announcementitem ALTER COLUMN image_storage_id TYPE uuid USING image_storage_id::uuid;
                    ALTER TABLE geiq_assessments_assessment ALTER COLUMN action_financial_assessment_file_id TYPE uuid USING action_financial_assessment_file_id::uuid;
                    ALTER TABLE geiq_assessments_assessment ALTER COLUMN structure_financial_assessment_file_id TYPE uuid USING structure_financial_assessment_file_id::uuid;
                    ALTER TABLE geiq_assessments_assessment ALTER COLUMN summary_document_file_id TYPE uuid USING summary_document_file_id::uuid;
                    ALTER TABLE job_applications_jobapplication ALTER COLUMN resume_id TYPE uuid USING resume_id::uuid;
                    ALTER TABLE siae_evaluations_evaluatedadministrativecriteria ALTER COLUMN proof_id TYPE uuid USING proof_id::uuid;
                    """,  # noqa: E501
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # Put back all constraints
                migrations.RunSQL(
                    """
                    CREATE INDEX "files_file_key_1c5dd06d_like" ON "files_file" ("key" varchar_pattern_ops);
                    ALTER TABLE antivirus_scan ADD CONSTRAINT antivirus_scan_file_id_48667630_fk_files_file_id FOREIGN KEY (file_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE approvals_prolongation ADD CONSTRAINT approvals_prolongati_report_file_id_3c95babf_fk_files_fil FOREIGN KEY (report_file_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE approvals_prolongationrequest ADD CONSTRAINT approvals_prolongati_report_file_id_7200b042_fk_files_fil FOREIGN KEY (report_file_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE communications_announcementitem ADD CONSTRAINT communications_annou_image_storage_id_6ce5930b_fk_files_fil FOREIGN KEY (image_storage_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE geiq_assessments_assessment ADD CONSTRAINT geiq_assessments_ass_action_financial_ass_8d3e6e9a_fk_files_fil FOREIGN KEY (action_financial_assessment_file_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE geiq_assessments_assessment ADD CONSTRAINT geiq_assessments_ass_structure_financial__20ceb0b7_fk_files_fil FOREIGN KEY (structure_financial_assessment_file_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE geiq_assessments_assessment ADD CONSTRAINT geiq_assessments_ass_summary_document_fil_9c3ad4a0_fk_files_fil FOREIGN KEY (summary_document_file_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE job_applications_jobapplication ADD CONSTRAINT job_applications_job_resume_id_98d390bf_fk_files_fil FOREIGN KEY (resume_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    ALTER TABLE siae_evaluations_evaluatedadministrativecriteria ADD CONSTRAINT siae_evaluations_eva_proof_id_d9c3e434_fk_files_fil FOREIGN KEY (proof_id) REFERENCES files_file (id) DEFERRABLE INITIALLY DEFERRED;
                    """,  # noqa: E501
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="file",
                    name="id",
                    field=models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False),
                ),
            ],
        )
    ]
