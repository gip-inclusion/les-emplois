"""

Here is the SQL request used to build the custom missions_ai_ehpad table.

Full specification of this table can be found in our "Documentation ITOU METABASE [Master doc]" shared google sheet.

No direct link here for safety reasons.

For more explanations about the mission / mei / emi tables, see `populate_metabase_fluxiae.py`.

"""
MISSIONS_AI_EPHAD_SQL_REQUEST = """
    select
        /* ILIKE means (case) Insensitive LIKE */
        case
            when m.mission_descriptif ilike '%EHPAD%'
            then TRUE
            else FALSE
        end as mission_has_ehpad_in_description,
        case
            when m.mission_descriptif ilike '%AIEHPAD%'
            then TRUE
            else FALSE
        end as mission_has_aiehpad_in_description,
        TO_DATE(m.mission_date_creation, 'DD/MM/YYYY') as mission_date_creation,
        TO_DATE(m.mission_date_modification, 'DD/MM/YYYY') as mission_date_modification,
        m.mission_id_ctr,
        m.mission_id_mis,
        mei.mei_dsm_id,
        TO_DATE(m.mission_date_debut, 'DD/MM/YYYY') as mission_date_debut,
        TO_DATE(m.mission_date_fin, 'DD/MM/YYYY') as mission_date_fin,
        m.mission_descriptif,
        m.mission_code_rome,
        CONCAT(
            r.code_rome, ' ', r.description_code_rome
        ) as mission_code_rome_complet,
        case
            when emi.emi_sme_mois is null
            then null
            else
                /* 15th day of the month instead of 1st day to avoid GT/GTE mistakes by metabase end user */
                TO_DATE(
                    CONCAT('15/', emi.emi_sme_mois, '/', emi.emi_sme_annee),
                    'DD/MM/YYYY'
                )
            end as mois,
        emi.emi_esm_etat_code as etat_saisie,
        TO_DATE(emi.emi_date_validation, 'DD/MM/YYYY') as date_validation,
        emi.emi_pph_id as id_personne,
        mei.mei_nombre_heures as nombre_heures,
        emi.emi_nb_heures_facturees as nombre_heures_facturees,
        s.structure_siret_actualise as siret_structure,
        s.itou_name as nom_structure,
        s.itou_post_code as code_postal_structure,
        s.itou_city as ville_structure,
        s.itou_department_code as departement_code_structure,
        s.itou_department as departement_structure,
        s.itou_region as region_structure,
        s.structure_code_naf as code_naf_structure,
        s.itou_kind as type_structure,
        s.itou_latitude as latitude_structure,
        s.itou_longitude as longitude_structure
    from
        /* TODO use lateral joins instead maybe */
        "fluxIAE_Missions" m
        left outer join "fluxIAE_MissionsEtatMensuelIndiv" mei
            on m.mission_id_mis = mei.mei_mis_id
        left outer join "fluxIAE_EtatMensuelIndiv" emi
            on mei.mei_dsm_id = emi.emi_dsm_id
        left outer join "fluxIAE_ContratMission" cm
            on m.mission_id_ctr = cm.contrat_id_ctr
        left outer join "fluxIAE_Structure" s
            on cm.contrat_id_structure = s.structure_id_siae
        left outer join "codes_rome" r
            on m.mission_code_rome = r.code_rome
    where m.mission_descriptif ilike '%EHPAD%'
"""
