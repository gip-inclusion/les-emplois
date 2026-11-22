// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=6978-36797
// source=itou/templates/eligibility/includes/iae/eligibility_badge.html (iae_eligibility_badge / approval_state_badge in itou/utils/templatetags/badges.py)
// component=Eligibilité
const figma = require('figma')
const instance = figma.selectedInstance

const eligible = instance.getEnum('Eligible', { False: false, True: true })
// [icon, colour classes, label] rendered by approval_state_badge for each ApprovalStatus.
const pass = instance.getEnum('Pass IAE', {
  False: null,
  True: ['ri-pass-valid-line', 'bg-success-lighter text-success', 'PASS IAE valide'],
  'Non démarré': ['ri-pass-valid-line', 'bg-success-lighter text-success', 'PASS IAE valide (non démarré)'],
  Suspendu: ['ri-pass-pending-line', 'bg-success-lighter text-success', 'PASS IAE valide (suspendu)'],
  Expired: ['ri-pass-expired-line', 'bg-danger-lighter text-danger', 'PASS IAE expiré'],
})
const size = instance.getEnum('Size up', { Off: 'badge-sm', On: 'badge-base' })
const include = `{% include "eligibility/includes/iae/eligibility_badge.html" with job_seeker=job_seeker eligibility_diagnosis=eligibility_diagnosis badge_size="${size}" only %}`

let example
if (pass) {
  // A valid PASS IAE takes precedence over the eligibility diagnosis.
  example = figma.html`${include}
{# Renders approval_state_badge: #}
<span class="badge ${size} rounded-pill ${pass[1]}">
    <i class="${pass[0]}" aria-hidden="true"></i>
    ${pass[2]}
</span>`
} else if (eligible) {
  example = figma.html`${include}
{# Renders iae_eligibility_badge is_eligible=True: #}
<span class="badge ${size} rounded-pill bg-success-lighter text-success">
    <i class="ri-check-line" aria-hidden="true"></i>
    Éligible à l’IAE
</span>`
} else {
  example = figma.html`${include}
{# Renders iae_eligibility_badge is_eligible=False (job seeker views pass for_job_seeker=True: bg-accent-02-lighter text-primary): #}
<span class="badge ${size} rounded-pill bg-warning-lighter text-warning">
    <i class="ri-error-warning-line" aria-hidden="true"></i>
    Éligibilité IAE à valider
</span>`
}

export default {
  example,
  id: 'eligibility-badge',
  metadata: { nestable: true },
}
