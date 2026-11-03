// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14443-7799
// source=itou/utils/templatetags/badges.py (job_application_state_badge)
// component=Candidature
const figma = require('figma')
const instance = figma.selectedInstance

// [JobApplicationState, colour classes, label]
const state = instance.getEnum('Status', {
  'Nouvelle candidature': ['NEW', 'bg-info', 'Nouvelle candidature'],
  'Candidature à l’étude': ['PROCESSING', 'bg-accent-03 text-primary', "Candidature à l'étude"],
  'Candidature en attente': ['POSTPONED', 'bg-accent-03 text-primary', 'Candidature en attente'],
  'Candidature acceptée': ['ACCEPTED', 'bg-success', 'Candidature acceptée'],
  'Candidature déclinée': ['REFUSED', 'bg-danger', 'Candidature déclinée'],
  'Embauché ailleurs': ['OBSOLETE', 'bg-primary', 'Embauché ailleurs'],
  'Embauche annulée': ['CANCELLED', 'bg-primary', 'Embauche annulée'],
})

export default {
  example: figma.html`{% load badges %}
{% job_application_state_badge job_application %}
{# Renders, for JobApplicationState.${state[0]}: #}
<span id="state_{{ job_application.pk }}" class="badge rounded-pill text-nowrap badge-sm mb-1 ${state[1]}">${state[2]}</span>`,
  id: 'job-application-state-badge',
  metadata: { nestable: true },
}
