# Generated by Django 5.0.3 on 2024-03-20 16:49

import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("approvals", "0003_approval_updated_at"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="prolongation",
            name="update_approval_end_at",
        ),
        pgtrigger.migrations.RemoveTrigger(
            model_name="suspension",
            name="update_approval_end_at",
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="prolongation",
            trigger=pgtrigger.compiler.Trigger(
                name="update_approval_end_at",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    func="\n                    --\n                    -- When a prolongation is inserted/updated/deleted, the end date\n                    -- of its approval is automatically pushed back or forth.\n                    --\n                    -- See:\n                    -- https://www.postgresql.org/docs/12/triggers.html\n                    -- https://www.postgresql.org/docs/12/plpgsql-trigger.html#PLPGSQL-TRIGGER-AUDIT-EXAMPLE\n                    --\n                    IF (TG_OP = 'DELETE') THEN\n                        -- At delete time, the approval's end date is pushed back if the prolongation\n                        -- was validated.\n                        UPDATE approvals_approval\n                        SET end_at = end_at - (OLD.end_at - OLD.start_at), updated_at=NOW()\n                        WHERE id = OLD.approval_id;\n                    ELSIF (TG_OP = 'INSERT') THEN\n                        -- At insert time, the approval's end date is pushed forward if the prolongation\n                        -- is validated.\n                        UPDATE approvals_approval\n                        SET end_at = end_at + (NEW.end_at - NEW.start_at), updated_at=NOW()\n                        WHERE id = NEW.approval_id;\n                    ELSIF (TG_OP = 'UPDATE') THEN\n                        -- At update time, the approval's end date is first reset before\n                        -- being pushed forward.\n                        UPDATE approvals_approval\n                        SET\n                          end_at = end_at - (OLD.end_at - OLD.start_at) + (NEW.end_at - NEW.start_at),\n                          updated_at=NOW()\n                        WHERE id = NEW.approval_id;\n                    END IF;\n                    RETURN NULL;\n                ",  # noqa: E501
                    hash="a536f93644930bcd1d91a494501716a95480e539",
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
                    func="\n                    --\n                    -- When a suspension is inserted/updated/deleted, the end date\n                    -- of its approval is automatically pushed back or forth.\n                    --\n                    -- See:\n                    -- https://www.postgresql.org/docs/12/triggers.html\n                    -- https://www.postgresql.org/docs/12/plpgsql-trigger.html#PLPGSQL-TRIGGER-AUDIT-EXAMPLE\n                    --\n                    IF (TG_OP = 'DELETE') THEN\n                        -- At delete time, the approval's end date is pushed back.\n                        UPDATE approvals_approval\n                        SET end_at = end_at - (OLD.end_at - OLD.start_at), updated_at=NOW()\n                        WHERE id = OLD.approval_id;\n                    ELSIF (TG_OP = 'INSERT') THEN\n                        -- At insert time, the approval's end date is pushed forward.\n                        UPDATE approvals_approval\n                        SET end_at = end_at + (NEW.end_at - NEW.start_at), updated_at=NOW()\n                        WHERE id = NEW.approval_id;\n                    ELSIF (TG_OP = 'UPDATE') THEN\n                        -- At update time, the approval's end date is first reset before\n                        -- being pushed forward, e.g.:\n                        --     * step 1 \"create new 90 days suspension\":\n                        --         * extend approval: approval.end_date + 90 days\n                        --     * step 2 \"edit 60 days instead of 90 days\":\n                        --         * reset approval: approval.end_date - 90 days\n                        --         * extend approval: approval.end_date + 60 days\n                        UPDATE approvals_approval\n                        SET\n                          end_at = end_at - (OLD.end_at - OLD.start_at) + (NEW.end_at - NEW.start_at),\n                          updated_at=NOW()\n                        WHERE id = NEW.approval_id;\n                    END IF;\n                    RETURN NULL;\n                ",  # noqa: E501
                    hash="b7b375ccb95197e49c611ad1522ab06896c13bb8",
                    operation="INSERT OR UPDATE OR DELETE",
                    pgid="pgtrigger_update_approval_end_at_6c264",
                    table="approvals_suspension",
                    when="AFTER",
                ),
            ),
        ),
    ]