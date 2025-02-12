# JavaScript

Comme nous ne disposons actuellement pas de tests exécutant le JavaScript, nous
essayons de limiter sa quantité sur notre site.

Le code JavaScript est ajouté dans ce dossier
[`itou/static/js/`](../itou/static/js/) ou, s’il n’est utile que pour une vue,
directement dans le template dans le `{% block script %}` à l’aide d'une
[`nonce`](https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/nonce):

``` {% block script %} {{ block.super }} <script nonce="{{ CSP_NONCE }}"> //
Insert smart code here </script> {% endblock %} ```

Les comportements largement réutilisables sont quant à eux ajoutés dans
[`itou/static/js/utils.js`](../itou/static/js/utils.js).

## `data-emplois-` prefix

`data-bs-` est le préfixe utilisé par bootstrap, `data-it-` celui utilisé par le
thème [itou](https://github.com/gip-inclusion/itou-theme).

Notre JS devrait utiliser le préfixe `data-emplois-` plutôt que des classes pour
identifier les éléments nécessitant un comportement spécifique.
