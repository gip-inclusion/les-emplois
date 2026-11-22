// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=9159-105
// source=itou/templates/components/c-info.html ({% component_info %}, as in apply/includes/job_application_accept_form.html)
// component=Information/On/On/Off
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Title')
const description = instance.getString('Description')

export default {
  example: figma.html`{% load components %}
{% component_info c_info__summary=c_info__summary c_info__detail=c_info__detail collapse_id="info-detail" opened=True %}
    {% fragment as c_info__summary %}
        ${title}
    {% endfragment %}
    {% fragment as c_info__detail %}
        <p>${description}</p>
    {% endfragment %}
{% endcomponent_info %}`,
  id: 'information-open',
  metadata: { nestable: true },
}
