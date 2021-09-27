/*
 
L'objectif est de créer une table agrégée avec par convention:
    - le nombre d'heures travaillées par les salariés en insertion
    - le nombre d'etp consommés
Ces indicateurs sont déclinés par type de public cible:
    - genre du salarié
    - RSA
    - niveau de formation du salarié
    - département et région de la structure
    - commune de la structure
    - établissement public territorial
    - département et région de l'annexe financière
  
Un filtre est appliqué pour ne récupérer que les données de la région Île-de-France puisqu'une expérimentation est en cours avec le département 93
 
 */

SELECT 
    emi.emi_pph_id  as identifiant_salarie,
    emi.emi_nb_heures_travail as nombre_heures_travaillees,
    emi.emi_part_etp as nombre_etp,
    emi.emi_sme_annee as annee_saisie,
    emi.emi_sme_mois as mois_saisie,
    make_date(cast(emi.emi_sme_annee as integer), cast(emi.emi_sme_mois as integer), 1) as date_saisie,
    case 
        when salarie.salarie_rci_libelle = 'M.' then 'Homme'
        else 'Femme'
    end genre_salarie, 
    case 
        when ctr_mis.contrat_salarie_rsa = 'OUI-M' then 'RSA majoré'
        when ctr_mis.contrat_salarie_rsa = 'OUI-NM' then 'RSA non majoré'
        when ctr_mis.contrat_salarie_rsa = 'NON' then 'Non'
        else 'Non renseigné'
    end rsa, 
    ctr_mis.contrat_id_structure,
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
        when niv_formation.rnf_libelle_niveau_form_empl = 'TROISIEME CYCLE OU ECOLE D''INGENIEUR' then 'k - Troisièmes cycle ou école d''ingénieur'
        else 'Autre'
    end niveau_formation_salarie, 
    structure.structure_denomination,
    structure.structure_adresse_admin_commune , 
    structure.structure_adresse_admin_code_insee,
    structure.nom_departement_structure,
    structure.nom_region_structure,
    af.af_id_annexe_financiere,
    af_numero_annexe_financiere, 
    af.af_numero_convention,
    af.nom_departement_af,
    af.nom_region_af,
    af.type_siae,
    ept.etablissement_Public_Territorial
from
    "fluxIAE_EtatMensuelIndiv" as emi
    left join "fluxIAE_ContratMission"  as ctr_mis
        on emi.emi_ctr_id = ctr_mis.contrat_id_ctr 
        and emi.emi_nb_heures_travail > 0 
    left join (
        select 
            distinct salarie_id, 
            salarie_rci_libelle
        from 
            "fluxIAE_Salarie"  
    ) as salarie
        on emi.emi_pph_id = salarie.salarie_id 
        and emi.emi_nb_heures_travail > 0
    left join 
        "fluxIAE_RefNiveauFormation" as niv_formation 
        on ctr_mis."contrat_niveau_de_formation_id" = niv_formation.rnf_id
    left join "fluxIAE_AnnexeFinanciere_v2" af
        on emi.emi_afi_id = af.af_id_annexe_financiere
        and af_etat_annexe_financiere_code in ('VALIDE', 'SAISI', 'PROVISOIRE', 'CLOTURE')
    left  join "fluxIAE_Structure_v2"  as structure
        on af.af_id_structure = structure.structure_id_siae
    /* On récupère le découpage établissement public territorial */   
    left join sa_ept ept on ept.code_comm = structure.structure_adresse_admin_code_insee
where
    /* on prend uniquement les salariés ayant travaillé au moins une heure dans la structure */
    emi.emi_nb_heures_travail > 0 and emi.emi_sme_annee >= (date_part('year', current_date) - 2 )
