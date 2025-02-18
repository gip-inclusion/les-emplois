import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0010_alter_approval_origin_prescriber_organization_kind_and_more"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="approval",
            name="create_employee_record_notification",
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="approval",
            trigger=pgtrigger.compiler.Trigger(
                name="create_employee_record_notification",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition='WHEN (OLD."end_at" IS DISTINCT FROM (NEW."end_at") OR OLD."start_at" IS DISTINCT FROM (NEW."start_at"))',  # noqa: E501
                    declare="DECLARE current_employee_record_id INT;",
                    func="\n                    -- If there is an \"UPDATE\" action on 'approvals_approval' table (Approval model object):\n                    -- create an `EmployeeRecordUpdateNotification` object for each PROCESSED `EmployeeRecord`\n                    -- linked to this approval\n                    IF (TG_OP = 'UPDATE') THEN\n                        -- Only for update operations:\n                        -- iterate through processed employee records linked to this approval\n                        FOR current_employee_record_id IN\n                            SELECT id FROM employee_record_employeerecord\n                            WHERE approval_number = NEW.number\n                            AND status IN (\n                                'PROCESSED', 'SENT', 'DISABLED'\n                            )\n                            LOOP\n                                -- Create `EmployeeRecordUpdateNotification` object\n                                -- with the correct type and status\n                                INSERT INTO employee_record_employeerecordupdatenotification\n                                    (employee_record_id, created_at, updated_at, status)\n                                SELECT current_employee_record_id, NOW(), NOW(), 'NEW'\n                                -- Update it if already created (UPSERT)\n                                -- On partial indexes conflict, the where clause of the index must be added here\n                                ON conflict(employee_record_id) WHERE status = 'NEW'\n                                DO\n                                -- Not exactly the same syntax as a standard update op\n                                UPDATE SET updated_at = NOW();\n                            END LOOP;\n                    END IF;\n                    RETURN NULL;\n                ",  # noqa: E501
                    hash="45442e1728b9b05d5e386610f84a528e6426a5ba",
                    operation='UPDATE OF "start_at", "end_at"',
                    pgid="pgtrigger_create_employee_record_notification_0b059",
                    table="approvals_approval",
                    when="AFTER",
                ),
            ),
        ),
    ]
