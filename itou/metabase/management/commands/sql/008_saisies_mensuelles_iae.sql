/* 
 
L'objectif est de créer une table agrégée avec plusieurs données retravaillées qui proviennent des saisies mensuelles des structures 
dans l'extranet asp.
Le choix a été fait d'avoir les données de l'année en cours + 2 ans d'historique
*/

with constantes as ( 
    /* historique de 2 ans */
    select 
        (max(emi.emi_sme_annee) - 2) as annee_en_cours_2,
        max(emi.emi_sme_annee) as annee_en_cours
    from 
        "fluxIAE_EtatMensuelIndiv" as emi
),
salarie_v0 as (
    select 
        distinct salarie.salarie_id, 
        salarie.salarie_adr_qpv_type,
        salarie.salarie_adr_is_zrr,
        salarie.salarie_annee_naissance, 
        salarie.salarie_codeinseecom,
        salarie.salarie_Commune, 
        salarie.salarie_rci_libelle,
        case 
            when trim(substr(trim(salarie.salarie_codeinseecom), 1, char_length(salarie.salarie_codeinseecom)-2)) like ('%97%')
            then trim(substr(trim(salarie.salarie_codeinseecom), 1, char_length(salarie.salarie_codeinseecom)-2)) 
            when trim(substr(trim(salarie.salarie_codeinseecom), 1, char_length(salarie.salarie_codeinseecom)-2)) like ('%98%') 
            then trim(substr(trim(salarie.salarie_codeinseecom), 1, char_length(salarie.salarie_codeinseecom)-2)) 
            else trim(substr(trim(salarie.salarie_codeinseecom), 1, char_length(salarie.salarie_codeinseecom)-3))
        end as code_departement_salarie
    from 
        "fluxIAE_Salarie" salarie
),
salarie as (
    select 
        salarie.*,
        case 
            when salarie.salarie_rci_libelle = 'M.' then 'Homme'
              else 'Femme'
        end genre_salarie, 
        (annee_en_cours - salarie.salarie_annee_naissance) as age_salarie,
        case 
           when (annee_en_cours - salarie.salarie_annee_naissance) <= 25 then 'a- Moins de 26 ans'
           when (annee_en_cours - salarie.salarie_annee_naissance) >= 26 and (annee_en_cours - salarie.salarie_annee_naissance) <= 30  then 'b- Entre 26 ans et 30 ans'
           when (annee_en_cours - salarie.salarie_annee_naissance) >= 31 and (annee_en_cours - salarie.salarie_annee_naissance) <= 50  then 'c- Entre 31 ans et 50 ans'
           when (annee_en_cours - salarie.salarie_annee_naissance) >= 51 then 'd- 51 ans et plus'
           else 'autre'
        end tranche_age,
        departement_com_salarie.nom_departement as departement_salarie,
        departement_com_salarie.nom_region as region_salarie 
    from constantes
    cross join 
        salarie_v0 as salarie
    left join 
        departements as departement_com_salarie
        on 
        code_departement_salarie = departement_com_salarie.code_departement
),
coordonnees_gps as (
    select 
        distinct code_insee,
        latitude,
        longitude 
    from 
        commune_GPS
)
select 
    distinct emi.emi_pph_id as identifiant_salarie, 
    make_date(cast(emi.emi_sme_annee as integer), cast(emi.emi_sme_mois as integer), 1) as date_saisie,
    to_date (emi.emi_date_validation ,'dd/mm/yyyy') as date_validation_declaration,
    emi.emi_part_etp as nombre_etp_consommes,
    emi.emi_nb_heures_travail as nombre_heures_travaillees, 
    emi.emi_afi_id as identifiant_annexe_fin,
    case 
        when ctr_mis.contrat_salarie_rsa = 'OUI-M' then 'RSA majoré'
        when ctr_mis.contrat_salarie_rsa = 'OUI-NM' then 'RSA non majoré'
        when ctr_mis.contrat_salarie_rsa = 'NON' then 'Non'
        else 'Non renseigné'
    end rsa, 
    ctr_mis.contrat_id_structure as id_structure_asp,
    to_date (ctr_mis.contrat_date_embauche ,'dd/mm/yyyy') as date_recrutement,
    case 
        when ctr_mis.contrat_salarie_rqth = 'true' then 'Oui'
        else 'Non'
    end rqth,
    concat(ctr_mis.contrat_code_rome, '-', code_rome.description_code_rome) as metier,
    case
        when niv_formation.rnf_libelle_niveau_form_empl = 'JAMAIS SCOLARISE' then 'a- Jamais scolarisé'
        when niv_formation.rnf_libelle_niveau_form_empl = 'PAS DE FORMATION AU DELA DE LA SCOLARITE OBLIG.' then 'b- Pas de formation au delà de la scolarité obligatoire'
        when niv_formation.rnf_libelle_niveau_form_empl = 'PERSONNES AVEC QUALIFICATIONS NON CERTIFIANTES' then 'c- Personnes avec qualifications non certifiantes'
        when niv_formation.rnf_libelle_niveau_form_empl = 'FORMATION COURTE D''UNE DUREE D''UN AN' then 'd- Formation courte d''une durée d''un an'
        when niv_formation.rnf_libelle_niveau_form_empl = 'FORMATION DE NIVEAU CAP OU BEP' then 'e- Formation de niveau CAP ou BEP'
        when niv_formation.rnf_libelle_niveau_form_empl = 'DIPLÔME OBTENU CAP OU BEP' then 'f- Diplôme obtenu CAP ou BEP'
        when niv_formation.rnf_libelle_niveau_form_empl = 'BREVET DE TECHNICIEN OU BACCALAUREAT PROFESSIONNEL' then 'g- Brevet de technicien ou baccalauréat professionnel'
        when niv_formation.rnf_libelle_niveau_form_empl = 'FORMATION DE NIVEAU BAC' then 'h- Formation de niveau BAC'
        when niv_formation.rnf_libelle_niveau_form_empl = 'FORMATION DE NIVEAU BTS OU DUT' then 'i- Formation de niveau BTS ou DUT'
        when niv_formation.rnf_libelle_niveau_form_empl = 'FORMATION DE NIVEAU LICENCE' then 'j- Formation de niveau licence'
        when niv_formation.rnf_libelle_niveau_form_empl = 'TROISIEME CYCLE OU ECOLE D''INGENIEUR' then 'k- Troisièmes cycle ou école d''ingénieur'
        else 'l- Autre'
    end niveau_formation_salarie, 
    to_date (emi.emi_date_fin_reelle ,'dd/mm/yyyy') as date_sortie,
    case 
        when salarie_adr_qpv_type = 'QP' then 'Oui'
        else 'Non'
    end qpv,
    case 
        when salarie_adr_is_zrr = 'true' then 'Oui'
        else 'Non'
    end zrr,
    salarie_annee_naissance,
    salarie.age_salarie,
    salarie_codeinseecom as code_insee_commune_resi_salarie,
    salarie_Commune as commune_resi_salarie, 
    salarie.genre_salarie,
    salarie.tranche_age,
    departement_salarie as departement_resi_salarie ,
    region_salarie as region_resi_salarie, 
    commune_salarie.latitude as latitude_commune_resi_salarie,
    commune_salarie.longitude as longitude_commune_resi_salarie,
    sortie.rms_libelle as motif_sortie,
    categoriesort.rcs_libelle as categorie_sortie,
    structure.structure_denomination,
    structure.structure_adresse_admin_commune as commune_structure, 
    structure.structure_adresse_admin_code_insee as code_insee_structure,
    structure.structure_siret_actualise as siret_structure, 
    structure.nom_departement_structure,
    structure.nom_region_structure,
    commune_structure.latitude as latitude_commune_structure,
    commune_structure.longitude as longitude_commune_structure,
    af.type_siae, 
    af.af_etp_postes_insertion,
    af.af_numero_convention,
    af.af_numero_annexe_financiere,
    af.nom_departement_af,
    af.nom_region_af,
    ept.etablissement_Public_Territorial,
    infra.nom_epci
from 
    constantes 
cross join 
    "fluxIAE_EtatMensuelIndiv" as emi 
    left join "fluxIAE_ContratMission" as ctr_mis 
        on emi.emi_ctr_id = ctr_mis.contrat_id_ctr and emi.emi_pph_id = ctr_mis.contrat_id_pph
        and emi.emi_sme_annee >= annee_en_cours_2
    left join public.codes_rome as code_rome 
        on code_rome.code_rome = ctr_mis.contrat_code_rome
    left join 
        "fluxIAE_RefNiveauFormation" as niv_formation 
        on ctr_mis."contrat_niveau_de_formation_id" = niv_formation.rnf_id
    left join salarie
        on emi.emi_pph_id = salarie.salarie_id 
        and emi.emi_sme_annee >= annee_en_cours_2 
    left join coordonnees_gps as commune_salarie 
        on salarie.salarie_codeinseecom = commune_salarie.code_insee
    left join "fluxIAE_RefMotifSort" as sortie 
        on emi.Emi_motif_sortie_id = sortie.rms_id
    left join  "fluxIAE_RefCategorieSort" as categoriesort
        on categoriesort.rcs_id = sortie.rcs_id
    left  join "fluxIAE_AnnexeFinanciere_v2" as af 
        on emi.emi_afi_id=af.af_id_annexe_financiere and af_etat_annexe_financiere_code in ('VALIDE', 'PROVISOIRE')
        and emi.emi_sme_annee >= annee_en_cours_2
        and af_mesure_dispositif_code not like '%MP%' 
        and af_mesure_dispositif_code not like '%FDI%'
    left join "fluxIAE_Structure_v2" as structure
        on af.af_id_structure = structure.structure_id_siae
    left join coordonnees_gps as commune_structure   
        on structure.structure_adresse_admin_code_insee = commune_structure.code_insee
/* On récupère le découpage établissement public territorial */   
    left join sa_ept ept on ept.code_comm = structure.structure_adresse_admin_code_insee
    left join sa_zones_infradepartementales infra on infra.code_commune = structure.structure_adresse_admin_code_insee
where emi.emi_sme_annee >= annee_en_cours_2
