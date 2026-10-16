// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=11542-1112
// source=les-emplois itou/common_apps/organizations/models.py (Organization.icon) + itou/templates/employee_record/includes/list_item.html (job seeker)
// component=User icon
const figma = require('figma')
const instance = figma.selectedInstance

// The square frame comes from the parent (.dropdown-item__summary, .c-box--results__summary…), not from the icon.
const icon = instance.getEnum('User', {
  Employeur: 'ri-community-line',
  Prescripteur: 'ri-home-smile-line',
  Usager: 'ri-user-line',
  'Institution partenaire': 'ri-government-line',
})

export default {
  example: figma.html`<i class="${icon}" aria-hidden="true"></i>`,
  id: 'user-icon',
  metadata: { nestable: true },
}
