import time

from django.db import migrations, models
from django.utils import timezone

from itou.utils.iterators import chunks


def forwards(apps, schema_editor):
    Approval = apps.get_model("approvals", "Approval")
    apps.get_model("approvals", "Suspension")
    approvals = []
    for approval in Approval.objects.filter(suspension__end_at__gte=timezone.localdate()).annotate(
        latest_suspension_end=models.Max("suspension__end_at")
    ):
        approval.suspended_until = approval.latest_suspension_end
        approvals.append(approval)
    for chunk in chunks(approvals, 1000):
        Approval.objects.bulk_update(chunk, fields=["suspended_until"])
        time.sleep(5)


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0010_add_eligibility_diagnosis_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="approval",
            name="suspended_until",
            field=models.DateField(editable=False, null=True, verbose_name="suspendu jusqu’à"),
        ),
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION update_approval_fields()
                    RETURNS TRIGGER
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        --
                        -- When a suspension is inserted/updated/deleted, the end date
                        -- of its approval is automatically pushed back or forth.
                        --
                        -- See:
                        -- https://www.postgresql.org/docs/14/triggers.html
                        -- https://www.postgresql.org/docs/14/plpgsql-trigger.html#PLPGSQL-TRIGGER-AUDIT-EXAMPLE
                        --
                        IF (TG_OP = 'DELETE') THEN
                            UPDATE approvals_approval
                            SET (end_at, suspended_until) = (
                                SELECT
                                -- Push back approval end date.
                                approvals_approval.end_at - (OLD.end_at - OLD.start_at),
                                -- Denormalize the suspension end date.
                                -- Note that suspensions cannot start in the future.
                                MAX(approvals_suspension.end_at)
                                FROM approvals_suspension
                                WHERE approval_id=OLD.approval_id
                            )
                            WHERE id = OLD.approval_id;
                        ELSIF (TG_OP = 'INSERT') THEN
                            UPDATE approvals_approval
                            SET (end_at, suspended_until) = (
                                SELECT
                                -- Push approval end date forward.
                                approvals_approval.end_at + (NEW.end_at - NEW.start_at),
                                MAX(approvals_suspension.end_at)
                                FROM approvals_suspension
                                WHERE approval_id=NEW.approval_id
                            )
                            WHERE id = NEW.approval_id;
                        ELSIF (TG_OP = 'UPDATE') THEN
                            -- At update time, the approval's end date is first reset before
                            -- being pushed forward, e.g.:
                            --     * step 1 "create new 90 days suspension":
                            --         * extend approval: approval.end_date + 90 days
                            --     * step 2 "edit 60 days instead of 90 days":
                            --         * reset approval: approval.end_date - 90 days
                            --         * extend approval: approval.end_date + 60 days
                            UPDATE approvals_approval
                            SET (end_at, suspended_until) = (
                                SELECT
                                approvals_approval.end_at - (OLD.end_at - OLD.start_at) + (NEW.end_at - NEW.start_at),
                                MAX(approvals_suspension.end_at)
                                FROM approvals_suspension
                                WHERE approval_id=NEW.approval_id
                            )
                            WHERE id = NEW.approval_id;
                        END IF;
                        RETURN NULL;
                    END;
                $$;

                CREATE OR REPLACE TRIGGER trigger_update_approval_end_at
                AFTER INSERT OR UPDATE OR DELETE ON approvals_suspension
                FOR EACH ROW
                EXECUTE FUNCTION update_approval_fields();

                ALTER TRIGGER trigger_update_approval_end_at
                ON approvals_suspension
                RENAME TO trigger_update_approval_fields;

                DROP FUNCTION update_approval_end_at;
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS trigger_update_approval_fields ON approvals_suspension;
                DROP FUNCTION IF EXISTS update_approval_fields();
            """,
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
