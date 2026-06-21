# This is included at the top of `/api/v1/redoc/`
CHANGELOG = """
# Changelog

## 2026-07-09

- endpoints `employee-records` et `employee-record-notifications` :
  champ `salarieLangueFrancaise`

  À partir du 09/07/2026, la signification du champ
  `salarieLangueFrancaise` peut être inversée avec l'en-tête HTTP
  `X-API-salarieLangueFrancaise-like-asp`.

  Entre le 01/11/2026 et le 15/11/2026, l'inversion du champ deviendra
  définitive, que l'en-tête HTTP soit présent ou non.

  **Les clients doivent être mis à jour avant le 01/11/2026** pour
  éviter un changement incompatible.

  Cf. la [note sur le champ
  `salarieLangueFrancaise`](#note-sur-le-champ-salarielanguefrancaise)
  plus bas pour plus de détails.
"""
