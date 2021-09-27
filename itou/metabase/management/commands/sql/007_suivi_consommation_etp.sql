/* 

L'objectif est de développer pour la DDETS un suivi des structures qui sous-consomment ou sur-consomment 
les etp par rapport à ce qui est subventionné.
Les DDETS pourront donc redistribuer les aides aux postes en se basant sur la consommation réelle des etp 
  
*/

select
    case 
        /* On calcule la moyenne des etp consommés depuis le début de l'année et on la compare avec le nombre d'etp 
        subventionné */
        when (sum(emi.emi_part_etp) / max(emi.emi_sme_mois)) < max(af.af_etp_postes_insertion) then 'sous-consommation'
        when (sum(emi.emi_part_etp) / max(emi.emi_sme_mois)) > max(af.af_etp_postes_insertion) then 'sur-consommation'
        else 'conforme'
    end consommation_ETP,
    sum(emi.emi_nb_heures_travail) as nb_heures_travaillees_depuis_debut_annee,
    sum(emi.emi_part_etp) / max(emi.emi_sme_mois) as moyenne_nb_etp_depuis_debut_annee,  
    dernier_mois_saisi_asp,
    structure.structure_denomination,
    structure.structure_id_siae,
    structure.structure_adresse_admin_commune, 
    structure.structure_adresse_admin_code_insee,
    structure.structure_siret_actualise,
    structure.nom_departement_structure,
    structure.nom_region_structure,
    af.af_id_annexe_financiere,
    af.type_siae, 
    af.af_numero_convention,
    af.nom_departement_af,
    af.nom_region_af,
    max(af.af_etp_postes_insertion) as nb_etp_subventionne
from suivi_saisies_dans_asp saisie_asp 
    left join "fluxIAE_EtatMensuelIndiv" emi 
        on saisie_asp.af_id_annexe_financiere = emi_afi_id  
    left join "fluxIAE_AnnexeFinanciere_v2" as af
        on saisie_asp.af_id_annexe_financiere = af.af_id_annexe_financiere  
        and af_etat_annexe_financiere_code in ('VALIDE', 'SAISI')
        /* Ne prendre que les déclarations mensuelles de l'année en cours */
        and emi.emi_sme_annee = date_part('year', current_date) 
        and date_part('year', to_date(af.af_date_debut_effet, 'dd/mm/yyyy')) = date_part('year', current_date) 
    left join "fluxIAE_Structure_v2" as structure
        on af.af_id_structure = structure.structure_id_siae
group by 
    dernier_mois_saisi_asp,
    structure.structure_denomination,
    structure.structure_id_siae,
    structure.structure_adresse_admin_commune, 
    structure.structure_adresse_admin_code_insee,
    structure.structure_siret_actualise,
    structure.nom_departement_structure,
    structure.nom_region_structure,
    af.af_id_annexe_financiere,
    af.type_siae, 
    af.af_numero_convention,
    af.nom_departement_af,
    af.nom_region_af
