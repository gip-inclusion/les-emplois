/*
  
L'objectif est de développer pour la DDETS un suivi des structures qui sous-consomment ou sur-consomment 
les etp par rapport à ce qui est conventionné.
Les DDETS pourront donc redistribuer les aides aux postes en se basant sur la consommation réelle des etp 
  
*/
with calcul_ETP as (
    select 
        /* En Janvier de l'année en cours, moyenne_nb_etp_depuis_debut_annee = (consommé sur l'année n-1) / (le dernier mois travaillé sur l'année n-1) */
        case 
            when (max(emi.emi_sme_annee) = date_part('year', current_date )- 1) then (sum(emi.emi_part_etp) / max(emi.emi_sme_mois))
            else (sum(emi.emi_part_etp) filter (where emi.emi_sme_annee = (date_part('year', current_date)))) 
                    / (max(emi.emi_sme_mois) filter (where emi.emi_sme_annee = (date_part('year', current_date))))
        end moyenne_nb_etp_depuis_debut_annee,
        case 
           when (max(emi.emi_sme_annee) = date_part('year', current_date )- 1) then max(af.af_etp_postes_insertion)
           else max(af.af_etp_postes_insertion) filter (where emi.emi_sme_annee = (date_part('year', current_date)))
        end nb_etp_subventionne,
        case 
           when (max(emi.emi_sme_annee) = date_part('year', current_date )- 1) then sum(emi.emi_nb_heures_travail)
           else sum(emi.emi_nb_heures_travail)  filter (where emi.emi_sme_annee = (date_part('year', current_date))) 
        end nb_heures_travaillees_depuis_debut_annee,
        saisie_asp.dernier_mois_saisi_asp,
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
    from suivi_saisies_dans_asp saisie_asp 
    left join "fluxIAE_EtatMensuelIndiv" emi 
        on saisie_asp.af_id_annexe_financiere = emi_afi_id  
    left join "fluxIAE_AnnexeFinanciere_v2" as af
        on saisie_asp.af_id_annexe_financiere = af.af_id_annexe_financiere  
        and af_etat_annexe_financiere_code in ('VALIDE'/*, 'SAISI'*/)
        /*On prend les déclarations mensuelles de l'année en cours + l'année n-1 */
        and emi.emi_sme_annee >= (date_part('year', current_date) - 1)
        and date_part('year', to_date(af.af_date_debut_effet, 'dd/mm/yyyy')) >= (date_part('year', current_date) - 1)
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
)
 select 
    *,
    case 
        /* On calcule la moyenne des etp consommés depuis le début de l'année et on la compare avec le nombre d'etp 
        conventionné */
        when moyenne_nb_etp_depuis_debut_annee < nb_etp_subventionne then 'sous-consommation'
        when moyenne_nb_etp_depuis_debut_annee > nb_etp_subventionne then 'sur-consommation'
        else 'conforme'
    end consommation_ETP
from 
    calcul_ETP
