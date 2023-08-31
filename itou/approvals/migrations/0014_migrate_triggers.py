import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0013_prolongationrequest_reminder_sent_at"),
        ("employee_record", "0005_stop_using_notification_type_field"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Suspension
            DROP TRIGGER IF EXISTS trigger_update_approval_end_at ON approvals_suspension;
            DROP FUNCTION IF EXISTS update_approval_end_at();
            -- Prolongation
            DROP TRIGGER IF EXISTS trigger_update_approval_end_at_for_prolongation ON approvals_prolongation;
            DROP FUNCTION IF EXISTS update_approval_end_at_for_prolongation();
            -- Employee record notification
            DROP TRIGGER IF EXISTS trigger_employee_record_approval_update_notification ON approvals_approval;
            DROP FUNCTION IF EXISTS create_employee_record_approval_notification();
            """,
            elidable=True,
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="prolongation",
            trigger=pgtrigger.compiler.Trigger(
                name="update_approval_end_at",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    func="\n                    --\n                    -- When a prolongation is inserted/updated/deleted, the end date\n                    -- of its approval is automatically pushed back or forth.\n                    --\n                    -- See:\n                    -- https://www.postgresql.org/docs/12/triggers.html\n                    -- https://www.postgresql.org/docs/12/plpgsql-trigger.html#PLPGSQL-TRIGGER-AUDIT-EXAMPLE\n                    --\n                    IF (TG_OP = 'DELETE') THEN\n                        -- At delete time, the approval's end date is pushed back if the prolongation\n                        -- was validated.\n                        UPDATE approvals_approval\n                        SET end_at = end_at - (OLD.end_at - OLD.start_at)\n                        WHERE id = OLD.approval_id;\n                    ELSIF (TG_OP = 'INSERT') THEN\n                        -- At insert time, the approval's end date is pushed forward if the prolongation\n                        -- is validated.\n                        UPDATE approvals_approval\n                        SET end_at = end_at + (NEW.end_at - NEW.start_at)\n                        WHERE id = NEW.approval_id;\n                    ELSIF (TG_OP = 'UPDATE') THEN\n                        -- At update time, the approval's end date is first reset before\n                        -- being pushed forward.\n                        UPDATE approvals_approval\n                        SET end_at = end_at - (OLD.end_at - OLD.start_at) + (NEW.end_at - NEW.start_at)\n                        WHERE id = NEW.approval_id;\n                    END IF;\n                    RETURN NULL;\n                ",  # noqa: E501
                    hash="68d9afbacb095f4426a5a5d0065acc16dd2cdc36",
                    operation="INSERT OR UPDATE OR DELETE",
                    pgid="pgtrigger_update_approval_end_at_d9288",
                    table="approvals_prolongation",
                    when="AFTER",
                ),
            ),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="suspension",
            trigger=pgtrigger.compiler.Trigger(
                name="update_approval_end_at",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    func="\n                    --\n                    -- When a suspension is inserted/updated/deleted, the end date\n                    -- of its approval is automatically pushed back or forth.\n                    --\n                    -- See:\n                    -- https://www.postgresql.org/docs/12/triggers.html\n                    -- https://www.postgresql.org/docs/12/plpgsql-trigger.html#PLPGSQL-TRIGGER-AUDIT-EXAMPLE\n                    --\n                    IF (TG_OP = 'DELETE') THEN\n                        -- At delete time, the approval's end date is pushed back.\n                        UPDATE approvals_approval\n                        SET end_at = end_at - (OLD.end_at - OLD.start_at)\n                        WHERE id = OLD.approval_id;\n                    ELSIF (TG_OP = 'INSERT') THEN\n                        -- At insert time, the approval's end date is pushed forward.\n                        UPDATE approvals_approval\n                        SET end_at = end_at + (NEW.end_at - NEW.start_at)\n                        WHERE id = NEW.approval_id;\n                    ELSIF (TG_OP = 'UPDATE') THEN\n                        -- At update time, the approval's end date is first reset before\n                        -- being pushed forward, e.g.:\n                        --     * step 1 \"create new 90 days suspension\":\n                        --         * extend approval: approval.end_date + 90 days\n                        --     * step 2 \"edit 60 days instead of 90 days\":\n                        --         * reset approval: approval.end_date - 90 days\n                        --         * extend approval: approval.end_date + 60 days\n                        UPDATE approvals_approval\n                        SET end_at = end_at - (OLD.end_at - OLD.start_at) + (NEW.end_at - NEW.start_at)\n                        WHERE id = NEW.approval_id;\n                    END IF;\n                    RETURN NULL;\n                ",  # noqa: E501
                    hash="051cd1df6304c50f45e9564921ac2c2b5b902d6d",
                    operation="INSERT OR UPDATE OR DELETE",
                    pgid="pgtrigger_update_approval_end_at_6c264",
                    table="approvals_suspension",
                    when="AFTER",
                ),
            ),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="approval",
            trigger=pgtrigger.compiler.Trigger(
                name="create_employee_record_notification",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."end_at" IS DISTINCT FROM (NEW."end_at") OR OLD."start_at" IS DISTINCT FROM (NEW."start_at"))',  # noqa: E501
                    declare="DECLARE current_employee_record_id INT;",
                    func="\n                    -- If there is an \"UPDATE\" action on 'approvals_approval' table (Approval model object):\n                    -- create an `EmployeeRecordUpdateNotification` object for each PROCESSED `EmployeeRecord`\n                    -- linked to this approval\n                    IF (TG_OP = 'UPDATE') THEN\n                        -- Only for update operations:\n                        -- iterate through processed employee records linked to this approval\n                        FOR current_employee_record_id IN\n                            SELECT id FROM employee_record_employeerecord\n                            WHERE approval_number = NEW.number\n                            AND status = 'PROCESSED'\n                            LOOP\n                                -- Create `EmployeeRecordUpdateNotification` object\n                                -- with the correct type and status\n                                INSERT INTO employee_record_employeerecordupdatenotification\n                                    (employee_record_id, created_at, updated_at, status)\n                                SELECT current_employee_record_id, NOW(), NOW(), 'NEW'\n                                -- Update it if already created (UPSERT)\n                                -- On partial indexes conflict, the where clause of the index must be added here\n                                ON conflict(employee_record_id) WHERE status = 'NEW'\n                                DO\n                                -- Not exactly the same syntax as a standard update op\n                                UPDATE SET updated_at = NOW();\n                            END LOOP;\n                    END IF;\n                    RETURN NULL;\n                ",  # noqa: E501
                    hash="fccf85ab0214d6439e66fdf5eeb3dd9c4b114561",
                    operation='UPDATE OF "start_at", "end_at"',
                    pgid="pgtrigger_create_employee_record_notification_0b059",
                    table="approvals_approval",
                    when="AFTER",
                ),
            ),
        ),
    ]
