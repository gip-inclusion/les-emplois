// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8329-32093
// source=les-emplois itou/templates/apply/includes/list_job_applications.html + list_table.html + list_tr.html
// component=Table
const figma = require('figma')
const instance = figma.selectedInstance

const columnCount = instance.getEnum('Columns', { 8: 8, 7: 7, 6: 6, 5: 5, 4: 4, 3: 3 })
const rows = instance.getEnum('- / + 5 rows', { On: 10, Off: 5 })
const scrollable = instance.getBoolean('Show Ascenseur')
const addColumn = instance.getBoolean('Ajouter une colonne')

// Columns of the received job applications list, in order; the last one holds the row actions.
const columns = [
  ['<th scope="col">Candidature de</th>', '<td><a class="btn-link" href="#">NINEY Pierre</a></td>'],
  ['<th scope="col">Émise le</th>', '<td>02/10/2026</td>'],
  ['<th scope="col">Employeur</th>', '<td>Une nouvelle chance</td>'],
  ['<th scope="col">Poste</th>', '<td>Agent de propreté</td>'],
  ['<th scope="col">Émetteur</th>', '<td><i class="ri-user-line me-1" aria-hidden="true"></i>L’usager lui-même</td>'],
  ['<th scope="col" class="text-nowrap">Critères administratifs</th>', '<td><i class="text-disabled">Aucun critère sélectionné</i></td>'],
  ['<th scope="col">Statut éligibilité</th>', '<td><span class="d-block">Un diagnostic doit être réalisé</span></td>'],
]
const actions = [
  '<th scope="col" class="text-end w-50px"><span class="visually-hidden">Actions possibles sur les candidatures</span></th>',
  '<td class="text-end w-50px align-middle"><a class="btn btn-sm btn-link btn-ico-only" href="#" data-bs-toggle="tooltip" data-bs-title="Voir sa candidature"><i class="ri-arrow-drop-right-line fs-lg" aria-label="Voir sa candidature"></i></a></td>',
]
const shown = columns.slice(0, columnCount - 1).concat([actions])
const headCells = shown.map((c) => c[0]).join('\n            ')
const bodyCells = shown.map((c) => c[1]).join('\n            ')
const addHead = addColumn ? '\n            <!-- Ajout de colonne : pas encore d\'équivalent dans les-emplois -->' : ''

const table = `<table class="table table-hover table-sortable">
    <caption class="visually-hidden">Liste des candidatures</caption>
    <thead>
        <tr>
            ${headCells}${addHead}
        </tr>
    </thead>
    <tbody>
        <!-- ${rows} lignes dans la maquette -->
        <tr class="align-top">
            ${bodyCells}
        </tr>
    </tbody>
</table>`

export default {
  example: scrollable ? figma.html`<div class="table-responsive mt-3 mt-md-4">
${table}
</div>` : figma.html`${table}`,
  id: 'table',
  metadata: { nestable: true },
}
