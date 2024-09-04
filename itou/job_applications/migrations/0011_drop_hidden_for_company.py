from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0010_set_jobapplication_archived_at"),
    ]

    operations = [
        # TODO: Squash with 0010_set_jobapplication_archived_at when applied.
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    """
                    UPDATE job_applications_jobapplication
                       SET archived_at=NOW()
                     WHERE hidden_for_company
                        AND archived_at IS NULL
                        AND state NOT IN ('accepted', 'prior_to_hire');

                    ALTER TABLE job_applications_jobapplication DROP COLUMN hidden_for_company;
                    """
                )
            ],
        ),
    ]
