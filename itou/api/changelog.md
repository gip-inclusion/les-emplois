### 2026-11-25

- endpoint `siaes_list` :

    Quand un `code_insee` est fourni, toutes les entreprises situées dans la
    ville correspondante sont renvoyées, indépendamment de `distance_max_km`.
    Si des entreprises se situent dans une autre ville à moins de
    `distance_max_km` du barycentre de la ville correspondant au `code_insee`
    elles sont toujours renvoyées.
    Le comportement change donc uniquement pour les entreprises situées dans
    la ville recherchée mais situées à plus de `distance_max_km` du barycentre.

### 2026-07-09

- endpoints `employee-records` :

    À partir du 09/07/2026, la signification du champ
    `salarieLangueFrancaise` peut être inversée avec l'en-tête HTTP
    `X-API-salarieLangueFrancaise-like-asp`.

    Entre le 01/01/2027 et le 15/01/2027, l'inversion du champ deviendra
    définitive, que l'en-tête HTTP soit présent ou non.

    **Les clients doivent être mis à jour avant le 01/01/2027** pour
    éviter un changement incompatible.

    Cf. la note sur le champ `salarieLangueFrancaise` dans la
    [documentation de l'API fiches salarié](/api/v1/documentation/#tag/employee-records)
    pour plus de détails.
