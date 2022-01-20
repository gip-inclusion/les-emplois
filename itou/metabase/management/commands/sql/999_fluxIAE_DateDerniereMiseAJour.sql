/*
Store fluxIAE latest update date in dedicated table for convenience.
This way we can show on metabase dashboards how fresh our data is.
*/

select
    max(TO_DATE(emi_date_creation, 'DD/MM/YYYY')) as date_derniere_mise_a_jour
from "fluxIAE_EtatMensuelIndiv"
