/* Cette table nous permet de suivre la consommation d'etp par structures, par rapport à leur conventionnement */
with mois_saisis as (
    select
        id_annexe_financiere,
        af_numero_annexe_financiere,
        -- On prend le mois maximal saisi +1 - le mois minimal saisi pour avoir le nombre de mois saisis
        (max(date_part('month', date_saisie))+ 1) - min(date_part('month', date_saisie)) as nombre_mois_saisis
    from
        suivi_etp_realises_v2
    group by
        id_annexe_financiere,
        af_numero_annexe_financiere
),
calcul_etp as (
    select
        distinct(etp.id_annexe_financiere),
        /* Utilisation de l'ID de l'annexe financière -> ID unique contrairement à la convention */
        etp.af_numero_annexe_financiere,
        etp.af_numero_convention,
        etp.af_etat_annexe_financiere_code,
        annee_af,
        dernier_mois_saisi_asp,
        nombre_mois_saisis,
        /* les deux conditions si dessous sont identiques, sauf que pour l'une on considère les ETPs mensuels et l'autre les annuels */
        sum(nombre_etp_consommes_reels_mensuels) as total_etp_mensuels_realises,
        sum(nombre_etp_consommes_reels_annuels) as total_etp_annuels_realises,
        -- Ici on utilise le nombre de mois saisis éviter d'écrire une formule à rallonge 
        case
            /* Sur les deux formules du dessous on sélectionne le dernier mois saisi pour avoir une moyenne mensuelle des ETPs consommés sur les années précédentes */
           -- Moyenne sur l'année N - 1
            when 
                (
                max(annee_af) = date_part (
                    'year',
                    current_date
                ) - 1
            ) 
            then 
                (
                sum(nombre_etp_consommes_reels_mensuels) / nombre_mois_saisis
            )
            -- Moyenne sur l'année N - 2
            when 
                (
                max(annee_af) = date_part('year', current_date) - 2
            ) 
            then 
                (
                sum(nombre_etp_consommes_reels_mensuels) / nombre_mois_saisis
            )
            -- Moyenne sur l'année actuelle
            /* Ici on lui demande de seulement prendre en compte les mois écoulés pour l'année en cours (donc en mars il divisera le total par 3) */
            else 
                sum(nombre_etp_consommes_reels_mensuels) 
            filter 
                (
            where
                annee_af = (
                    date_part('year', current_date)
                )
            ) / nombre_mois_saisis
        end moyenne_nb_etp_mensuels_depuis_debut_annee,
        case
        -- Moyenne sur l'année N-1
            when 
                (
                max(annee_af) = date_part (
                    'year',
                    current_date
                ) - 1
            ) 
            then 
                (
                sum(nombre_etp_consommes_reels_annuels) / nombre_mois_saisis
            )
        -- Moyenne sur l'année N-2
            when 
                (
                max(annee_af) = date_part('year', current_date) - 2
            ) 
            then 
                (
                sum(nombre_etp_consommes_reels_annuels) / nombre_mois_saisis
            )
        -- Moyenne sur l'année actuelle
            else 
                sum(nombre_etp_consommes_reels_annuels) 
                    filter (
            where
                annee_af = (
                    date_part('year', current_date)
                )
            ) / nombre_mois_saisis
        end moyenne_nb_etp_annuels_depuis_debut_annee,
        "effectif_mensuel_conventionné",
        "effectif_annuel_conventionné",
        etp.duree_annexe,
        etp.type_structure,
        etp.structure_denomination,
        etp.code_departement_af,
        etp.nom_departement_af,
        etp.nom_region_af
    from
        suivi_etp_conventionnes_v2 etp
    left join suivi_etp_realises_v2 etp_c on
        etp.id_annexe_financiere = etp_c.id_annexe_financiere
        and etp.af_numero_convention = etp_c.af_numero_convention
        and etp.af_numero_annexe_financiere = etp_c.af_numero_annexe_financiere
        and date_part('year', etp_c.date_saisie) = annee_af
        /* bien penser à joindre sur l'année pour éviter que l'on se retrouve avec années de conventionnement qui correspondent pas */
    left join suivi_saisies_dans_asp sasp on
        sasp.af_id_annexe_financiere = etp.id_annexe_financiere
    left join mois_saisis ms on
        ms.id_annexe_financiere = etp.id_annexe_financiere
    group by
        dernier_mois_saisi_asp,
        duree_annexe,
        nombre_mois_saisis,
        etp.id_annexe_financiere,
        etp.af_numero_convention,
        etp.af_numero_annexe_financiere,
        etp.af_etat_annexe_financiere_code,
        "effectif_mensuel_conventionné",
        "effectif_annuel_conventionné",
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
                conventionnés */
        when moyenne_nb_etp_mensuels_depuis_debut_annee < "effectif_mensuel_conventionné" then 'sous-consommation'
        when moyenne_nb_etp_mensuels_depuis_debut_annee > "effectif_mensuel_conventionné" then 'sur-consommation'
        else 'conforme'
    end consommation_ETP
from
    calcul_etp