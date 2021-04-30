select 
    * , 
    substr(
    	af_mesure_dispositif_code, 1, char_length(af_mesure_dispositif_code) - 3
    ) as "Type_SIAE"
from "fluxIAE_AnnexeFinanciere"
