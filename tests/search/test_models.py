import pytest
from django.db import IntegrityError

from tests.cities.factories import create_city_vannes
from tests.search.factories import SavedSearchFactory


class TestSavedSearch:
    def test_name_user_constraint(self):
        create_city_vannes()
        user = SavedSearchFactory(name="Vannes").user

        # Other user, same name
        SavedSearchFactory(name="Vannes")
        # Same user, other name
        SavedSearchFactory(user=user, name="Vannes 2")
        with pytest.raises(
            IntegrityError, match='duplicate key value violates unique constraint "unique_savedsearch_name_per_user"'
        ):
            # Same user, same name
            SavedSearchFactory(user=user, name="Vannes")
