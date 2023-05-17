from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee_record", "0004_asp_exchange_information_abstract_model"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeerecordupdatenotification",
            name="notification_type",
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name="Type de notification"),
        ),
        migrations.AddConstraint(
            model_name="employeerecordupdatenotification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "NEW")), fields=("employee_record",), name="unique_new_employee_record"
            ),
        ),
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION create_employee_record_approval_notification()
                RETURNS TRIGGER AS $approval_notification$
                DECLARE
                    -- Must be declared for iterations
                    current_employee_record_id INT;
                BEGIN
                    -- If there is an "UPDATE" action on 'approvals_approval' table (Approval model object):
                    -- create an `EmployeeRecordUpdateNotification` object for each PROCESSED `EmployeeRecord`
                    -- linked to this approval
                    IF (TG_OP = 'UPDATE') THEN
                        -- Only for update operations:
                        -- iterate through processed employee records linked to this approval
                        FOR current_employee_record_id IN
                            SELECT id FROM employee_record_employeerecord
                            WHERE approval_number = NEW.number
                            AND status = 'PROCESSED'
                            LOOP
                                -- Create `EmployeeRecordUpdateNotification` object
                                -- with the correct type and status
                                INSERT INTO employee_record_employeerecordupdatenotification
                                    (employee_record_id, created_at, updated_at, status)
                                SELECT current_employee_record_id, NOW(), NOW(), 'NEW'
                                -- Update it if already created (UPSERT)
                                -- On partial indexes conflict, the where clause of the index must be added here
                                ON conflict(employee_record_id) WHERE status = 'NEW'
                                DO
                                -- Not exactly the same syntax as a standard update op
                                UPDATE SET updated_at = NOW();
                            END LOOP;
                    END IF;
                    RETURN NULL;
                END;
            $approval_notification$ LANGUAGE plpgsql;
            """,
            reverse_sql="""
            CREATE OR REPLACE FUNCTION create_employee_record_approval_notification()
                RETURNS TRIGGER AS $approval_notification$
                DECLARE
                    -- Must be declared for iterations
                    current_employee_record_id INT;
                BEGIN
                    -- If there is an "UPDATE" action on 'approvals_approval' table (Approval model object):
                    -- create an `EmployeeRecordUpdateNotification` object for each PROCESSED `EmployeeRecord`
                    -- linked to this approval
                    IF (TG_OP = 'UPDATE') THEN
                        -- Only for update operations:
                        -- iterate through processed employee records linked to this approval
                        FOR current_employee_record_id IN
                            SELECT id FROM employee_record_employeerecord
                            WHERE approval_number = NEW.number
                            AND status = 'PROCESSED'
                            LOOP
                                -- Create `EmployeeRecordUpdateNotification` object
                                -- with the correct type and status
                                INSERT INTO employee_record_employeerecordupdatenotification
                                    (employee_record_id, created_at, updated_at, status, notification_type)
                                SELECT current_employee_record_id, NOW(), NOW(), 'NEW', 'APPROVAL'
                                -- Update it if already created (UPSERT)
                                -- On partial indexes conflict, the where clause of the index must be added here
                                ON conflict(employee_record_id, notification_type) WHERE status = 'NEW'
                                DO
                                -- Not exactly the same syntax as a standard update op
                                UPDATE SET updated_at = NOW();
                            END LOOP;
                    END IF;
                    RETURN NULL;
                END;
            $approval_notification$ LANGUAGE plpgsql;
            """,
        ),
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS partial_unique_new_notification;",
            reverse_sql="""
            CREATE UNIQUE INDEX partial_unique_new_notification
            ON employee_record_employeerecordupdatenotification (employee_record_id, notification_type)
            WHERE status = 'NEW';
            """,
        ),
    ]
