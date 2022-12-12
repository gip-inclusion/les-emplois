/* Cette table nous permet de suivre la consommation d'etp par structures, par rapport à leur conventionnement */
with calcul_etp as (
select 
    distinct(etp.id_annexe_financiere),
    etp.af_numero_annexe_financiere,
    etp.af_numero_convention,
    annee_af,
    sum(nombre_etp_consommes_reels_mensuels) as total_etp_annuels_realises,
    sum(nombre_etp_consommes_reels_annuels) as total_etp_mensuels_realises,
    case 
        when (max(annee_af) = date_part ('year', current_date )- 1) then (sum(nombre_etp_consommes_reels_mensuels) / max(date_part('month',etp_c.date_saisie)))
        when (max(annee_af) = date_part('year', current_date )- 2) then (sum(nombre_etp_consommes_reels_mensuels) / max(date_part('month',etp_c.date_saisie)))
        else sum(nombre_etp_consommes_reels_mensuels) filter (where annee_af = (date_part('year', current_date))) 
                / (max(date_part('month',etp_c.date_saisie)) filter (where annee_af = (date_part('year', current_date))))
        end moyenne_nb_etp_annuels_depuis_debut_annee,
    case 
        when (max(annee_af) = date_part ('year', current_date )- 1) then (sum(nombre_etp_consommes_reels_annuels) / max(date_part('month',etp_c.date_saisie)))
        when (max(annee_af) = date_part('year', current_date )- 2) then (sum(nombre_etp_consommes_reels_annuels) / max(date_part('month',etp_c.date_saisie)))
        else sum(nombre_etp_consommes_reels_annuels) filter (where annee_af = (date_part('year', current_date))) 
                / (max(date_part('month',etp_c.date_saisie)) filter (where annee_af = (date_part('year', current_date))))
        end moyenne_nb_etp_mensuels_depuis_debut_annee,
    (etp.nombre_etp_conventionnés) as etp_conventionnés, 
    max(date_part('month',etp_c.date_saisie)) as mois_max,
    etp.type_structure,
    etp.structure_denomination,
    etp.code_departement_af,
    etp.nom_departement_af,
    etp.nom_region_af
from
    suivi_etp_conventionnes_v2 etp
left join suivi_etp_realises_v2 etp_c 
    on
    etp.id_annexe_financiere = etp_c.id_annexe_financiere
    and
    etp.af_numero_convention = etp_c.af_numero_convention
    and
    etp.af_numero_annexe_financiere = etp_c.af_numero_annexe_financiere
    and
    date_part('year',etp_c.date_saisie) = annee_af /* bien penser à joindre sur l'année pour éviter que l'on se retrouve avec années de conventionnement qui correspondent pas */
group by
    etp.id_annexe_financiere,
    etp.af_numero_convention,
    etp.af_numero_annexe_financiere,
    etp_conventionnés,
    annee_af,
    etp.type_structure,
    etp.structure_denomination,
    etp.code_departement_af,
    etp.nom_departement_af,
    etp.nom_region_af
)

select 
    *,
    case 
        /* On calcule la moyenne des etp consommés depuis le début de l'année et on la compare avec le nombre d'etp 
        conventionné */
        when moyenne_nb_etp_mensuels_depuis_debut_annee < etp_conventionnés then 'sous-consommation'
        when moyenne_nb_etp_mensuels_depuis_debut_annee > etp_conventionnés then 'sur-consommation'
        else 'conforme'
    end consommation_ETP
from 
    calcul_etp