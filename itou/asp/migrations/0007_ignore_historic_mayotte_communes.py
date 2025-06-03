from django.db import migrations


# Only the code starting with 985 seems to have a systemic problem.
# Found with:
# SELECT id, substring(code from 0 for 4) AS dept, code AS old_code, name
# FROM asp_commune
# WHERE code >= '97100'
# AND substring(code from 0 for 4) NOT IN (
#   '971', '972', '973', '974', '975', '976', '977', '978', '984', '986', '987', '988', '989'
# )
# ;
#
# And confirmed with:
# SELECT status, asp_processing_code, asp_processing_label, COUNT(*)
# FROM employee_record_employeerecord
# WHERE substring(archived_json->'personnePhysique'->'codeComInsee'->>'codeComInsee' for 3) = '985'
# GROUP BY 1, 2, 3
# ;
#
# Also check that we did have a 1-1 mapping between both commune list with:
# SELECT e.old_code, c.code AS new_code, e.name AS old_name, c.name AS new_name, e.id, c.id
# FROM (
#   SELECT id, substring(code from 0 for 4) AS dept, code AS old_code, name
#   FROM asp_commune
#   WHERE code >= '97100'
#   AND substring(code from 0 for 4) NOT IN (
#     '971', '972', '973', '974', '975', '976', '977', '978', '984', '986', '987', '988', '989'
#   )
# ) AS e
# LEFT JOIN asp_commune AS c
# ON
#   regexp_replace(c.name, '[^\w]', '') = regexp_replace(e.name, '[^\w]', '')
#   AND c.code != e.old_code
# ORDER BY old_code, new_code
# ;


def forward(apps, editor):
    Commune = apps.get_model("asp", "Commune")
    Commune.objects.filter(code__startswith="985", ignore=False).update(ignore=True)


def backward(apps, editor):
    Commune = apps.get_model("asp", "Commune")
    Commune.unfiltered_objects.filter(code__startswith="985", ignore=True).update(ignore=False)


class Migration(migrations.Migration):
    dependencies = [
        ("asp", "0006_alter_commune_managers_commune_ignore"),
    ]

    operations = [
        migrations.RunPython(forward, backward, elidable=False),
    ]
