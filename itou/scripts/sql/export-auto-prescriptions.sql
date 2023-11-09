-- Demande : Extraction de l'ensemble des PASS IAE délivré en auto-diagnostic en 2022.
-- (diagnostic réalisé par la SIAE destinataire)
--
CREATE TEMP VIEW tmp AS (
    SELECT
    to_company.id as "Id établissement",
    to_company.siret as "SIRET établissement",
    convention.siret_signature as "SIRET à la signature",
    to_company.kind as "Type établissement",
    to_company.name as "Nom établissement",
    to_company.department as "Département établissement",
    a.number as "Numero pass",
    a.start_at as "Date début PASS",
    a.end_at as "Date fin PASS",
    u.id as "id candidat",
    u.first_name as "Prénom candidat",
    u.last_name as "Nom candidat",
    ja.hiring_start_at as "Date d’embauche",
    diagnostic_criterions.all_criterions as "Machin"
    FROM job_applications_jobapplication as ja
    INNER join approvals_approval a ON a.id = ja.approval_id
    INNER JOIN companies_company as to_company on to_company.id = ja.to_company_id
    INNER JOIN companies_siaeconvention as convention on convention.id = to_company.convention_id
    INNER JOIN users_user u ON u.id = ja.job_seeker_id
    INNER JOIN (
        select
            diag.job_seeker_id,
            diag.author_siae_id,
            string_agg(criteria.name, ',') as all_criterions
        from eligibility_eligibilitydiagnosis as diag
        LEFT JOIN eligibility_selectedadministrativecriteria sel_criteria
            on sel_criteria.eligibility_diagnosis_id = diag.id
        LEFT JOIN eligibility_administrativecriteria criteria
            on criteria.id = sel_criteria.administrative_criteria_id
        group by diag.id
    ) diagnostic_criterions ON diagnostic_criterions.job_seeker_id = ja.job_seeker_id and diagnostic_criterions.author_siae_id = ja.to_company_id
    where
        ja.state = 'accepted'
        and ja.approval_id is not null
        and extract(year from ja.created_at) = 2022
);

\copy (SELECT * FROM tmp) to 'export-auto-prescriptions-2022-10-11.csv' with csv header;

DROP VIEW tmp;

