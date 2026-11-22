// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10409-526
// source=les-emplois itou/templates/employee_record/includes/list_item.html (job seeker), itou/templates/companies/includes/_card_siae.html (organization), itou/utils/templatetags/badges.py (iae_eligibility_badge)
// component=User card
const figma = require('figma')
const instance = figma.selectedInstance

const name = instance.getString('Nom')
const detail = instance.getString('Détail')
// Icons follow the UI-Kit; in code an organization uses organization.icon (ri-home-smile-line for every prescriber).
const type = instance.getEnum('Type', {
  Usager: 'ri-user-line',
  Employeur: 'ri-community-line',
  Orienteur: 'ri-group-line',
  'Prescripteur habilité': 'ri-home-smile-line',
})

let example
if (type === 'ri-user-line') {
  example = figma.html`<div class="c-box--results__summary flex-grow-1">
    <i class="ri-user-line" aria-hidden="true"></i>
    <div>
        <h3>${name}</h3>
        <div class="d-flex flex-column flex-md-row align-items-start align-items-md-end gap-1 gap-md-2">
            <span>
                <i class="ri-map-pin-2-line fw-normal me-1" aria-hidden="true"></i>${detail}
            </span>
            <span class="badge badge-xs rounded-pill bg-success-lighter text-success">
                <i class="ri-check-line" aria-hidden="true"></i>
                Éligible à l’IAE
            </span>
        </div>
    </div>
</div>`
} else {
  example = figma.html`<div class="c-box--results__summary">
    <i class="${type}" aria-hidden="true"></i>
    <div>
        <span>${detail}</span>
        <h3>${name}</h3>
    </div>
</div>`
}

export default {
  example,
  id: 'user-card',
  metadata: { nestable: true },
}
