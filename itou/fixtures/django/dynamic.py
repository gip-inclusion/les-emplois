from itou.geiq_assessments import fixtures as geiq_assessments_fixtures
from itou.siae_evaluations import fixtures as siae_evaluations_fixtures


def load_dynamic():
    siae_evaluations_fixtures.load_data()
    geiq_assessments_fixtures.update_campaign_dates()
