"""The barriers a pro support report names, with their icons: shared by the side drawers that show them."""

from itou.companies.enums import ProSupportReportBarrier as Barrier


# « Autre frein »: free text in the report.
OTHER = "OTHER"

BARRIER_ICONS = {
    Barrier.HEALTH: "ri-heart-pulse-line",
    Barrier.MOBILITY: "ri-car-line",
    Barrier.FAMILY: "ri-parent-line",
    Barrier.FINANCIAL: "ri-wallet-3-line",
    Barrier.DIGITAL: "ri-computer-line",
    Barrier.LEGAL: "ri-scales-3-line",
    Barrier.LITERACY: "ri-book-open-line",
    OTHER: "ri-question-line",
}
