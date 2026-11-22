// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=7872-36049
// source=itou/templates/apply/includes/job_application_answers.html (<small> label + blockquote.blockquote)
// component=Citation
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')

export default {
  example: figma.html`<small>Libellé</small>
<blockquote class="blockquote mt-2 mb-0">
    ${text}
</blockquote>`,
  id: 'quote',
  metadata: { nestable: true },
}
