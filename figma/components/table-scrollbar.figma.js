// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10768-5108
// source=les-emplois itou/templates/apply/includes/list_job_applications.html (the native scrollbar of .table-responsive)
// component=Ascenseur
const figma = require('figma')

export default {
  example: figma.html`<div class="table-responsive">
    <!-- <table class="table">…</table> : la barre de défilement horizontale est celle du navigateur -->
</div>`,
  id: 'table-scrollbar',
  metadata: { nestable: true },
}
