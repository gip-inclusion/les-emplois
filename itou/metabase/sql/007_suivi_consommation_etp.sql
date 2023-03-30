/*

L'objectif est de développer pour la DDETS un suivi des structures qui sous-consomment ou sur-consomment
les etp par rapport à ce qui est conventionné.
Les DDETS pourront donc redistribuer les aides aux postes en se basant sur la consommation réelle des etp

*/
with CALCUL_ETP as (
    select
        /* En Janvier de l'année en cours, moyenne_nb_etp_depuis_debut_annee = (consommé sur l'année n-1) / (le dernier mois travaillé sur l'année n-1) */
        SAISIE_ASP.DERNIER_MOIS_SAISI_ASP,
        STRUCTURE.STRUCTURE_DENOMINATION,
        STRUCTURE.STRUCTURE_ID_SIAE,
        STRUCTURE.STRUCTURE_ADRESSE_ADMIN_COMMUNE,
        STRUCTURE.STRUCTURE_ADRESSE_ADMIN_CODE_INSEE,
        STRUCTURE.STRUCTURE_SIRET_ACTUALISE,
        STRUCTURE.NOM_DEPARTEMENT_STRUCTURE,
        STRUCTURE.NOM_REGION_STRUCTURE,
        AF.AF_ID_ANNEXE_FINANCIERE,
        AF.TYPE_SIAE,
        AF.AF_NUMERO_CONVENTION,
        AF.NOM_DEPARTEMENT_AF,
        AF.NOM_REGION_AF,
        case
            when (max(EMI.EMI_SME_ANNEE) = date_part('year', current_date) - 1) then (sum(EMI.EMI_PART_ETP) / max(EMI.EMI_SME_MOIS))
            else
                (sum(EMI.EMI_PART_ETP) filter (where EMI.EMI_SME_ANNEE = (date_part('year', current_date))))
                / (max(EMI.EMI_SME_MOIS) filter (where EMI.EMI_SME_ANNEE = (date_part('year', current_date))))
        end as MOYENNE_NB_ETP_DEPUIS_DEBUT_ANNEE,
        case
            when (max(EMI.EMI_SME_ANNEE) = date_part('year', current_date) - 1) then max(AF.AF_ETP_POSTES_INSERTION)
            else max(AF.AF_ETP_POSTES_INSERTION) filter (where EMI.EMI_SME_ANNEE = (date_part('year', current_date)))
        end as NB_ETP_SUBVENTIONNE,
        case
            when (max(EMI.EMI_SME_ANNEE) = date_part('year', current_date) - 1) then sum(EMI.EMI_NB_HEURES_TRAVAIL)
            else sum(EMI.EMI_NB_HEURES_TRAVAIL) filter (where EMI.EMI_SME_ANNEE = (date_part('year', current_date)))
        end as NB_HEURES_TRAVAILLEES_DEPUIS_DEBUT_ANNEE
    from SUIVI_SAISIES_DANS_ASP as SAISIE_ASP
    left join "fluxIAE_EtatMensuelIndiv" as EMI
        on SAISIE_ASP.AF_ID_ANNEXE_FINANCIERE = EMI_AFI_ID
    left join "fluxIAE_AnnexeFinanciere_v2" as AF
        on
            SAISIE_ASP.AF_ID_ANNEXE_FINANCIERE = AF.AF_ID_ANNEXE_FINANCIERE
            and AF_ETAT_ANNEXE_FINANCIERE_CODE in ('VALIDE'/*, 'SAISI'*/)
            /*On prend les déclarations mensuelles de l'année en cours + l'année n-1 */
            and EMI.EMI_SME_ANNEE >= (date_part('year', current_date) - 1)
            and date_part('year', to_date(AF.AF_DATE_DEBUT_EFFET, 'dd/mm/yyyy')) >= (date_part('year', current_date) - 1)
    left join "fluxIAE_Structure_v2" as STRUCTURE
        on AF.AF_ID_STRUCTURE = STRUCTURE.STRUCTURE_ID_SIAE
    group by
        DERNIER_MOIS_SAISI_ASP,
        STRUCTURE.STRUCTURE_DENOMINATION,
        STRUCTURE.STRUCTURE_ID_SIAE,
        STRUCTURE.STRUCTURE_ADRESSE_ADMIN_COMMUNE,
        STRUCTURE.STRUCTURE_ADRESSE_ADMIN_CODE_INSEE,
        STRUCTURE.STRUCTURE_SIRET_ACTUALISE,
        STRUCTURE.NOM_DEPARTEMENT_STRUCTURE,
        STRUCTURE.NOM_REGION_STRUCTURE,
        AF.AF_ID_ANNEXE_FINANCIERE,
        AF.TYPE_SIAE,
        AF.AF_NUMERO_CONVENTION,
        AF.NOM_DEPARTEMENT_AF,
        AF.NOM_REGION_AF
)

select
    *,
    case
        /* On calcule la moyenne des etp consommés depuis le début de l'année et on la compare avec le nombre d'etp
        conventionné */
        when MOYENNE_NB_ETP_DEPUIS_DEBUT_ANNEE < NB_ETP_SUBVENTIONNE then 'sous-consommation'
        when MOYENNE_NB_ETP_DEPUIS_DEBUT_ANNEE > NB_ETP_SUBVENTIONNE then 'sur-consommation'
        else 'conforme'
    end as CONSOMMATION_ETP
from
    CALCUL_ETP
