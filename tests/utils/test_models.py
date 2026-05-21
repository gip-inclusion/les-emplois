import pytest
from django.apps import apps
from django.db import ProgrammingError, connection, transaction
from psycopg.types.json import Jsonb

from itou.companies.models import Company
from itou.users.models import JobSeekerProfile, User
from itou.utils import triggers
from itou.utils.models import AbstractFieldsHistoryModel
from tests.companies.factories import CompanyFactory
from tests.users.factories import ItouStaffFactory, JobSeekerProfileFactory


FIELDS_HISTORY_MODELS_TO_TEST_PARAMS = {
    Company: {
        "factory": CompanyFactory,
        "test_field": "siret",
        "initial": "00000000000000",
        "update": "00000000000001",
    },
    JobSeekerProfile: {
        "factory": JobSeekerProfileFactory,
        "test_field": "asp_uid",
        "initial": "0" * 30,
        "update": "1" * 30,
    },
    User: {
        "factory": ItouStaffFactory,
        "test_field": "email",
        "initial": "foo@example.com",
        "update": "bar@example.com",
    },
}


class TestAbstractFieldsHistoryModel:
    def test_FIELDS_HISTORY_MODELS_TO_TEST_PARAMS(self):
        # Check that the dictionnary is up-to-date
        assert {model for model in apps.get_models() if issubclass(model, AbstractFieldsHistoryModel)} == set(
            FIELDS_HISTORY_MODELS_TO_TEST_PARAMS
        )

    @pytest.mark.parametrize("model", FIELDS_HISTORY_MODELS_TO_TEST_PARAMS)
    def test_triggers(self, model):
        # Check that the model is properly configured, especially its Meta
        assert model._meta.get_field("fields_history")
        assert triggers.FieldsHistory in [type(trigger) for trigger in model._meta.triggers]

    @pytest.mark.parametrize("model", FIELDS_HISTORY_MODELS_TO_TEST_PARAMS)
    def test_field_history_update_raise(self, model):
        instance = FIELDS_HISTORY_MODELS_TO_TEST_PARAMS[model]["factory"]()
        assert instance.fields_history == []

        with pytest.raises(ProgrammingError, match='Modification du champ "fields_history" interdit'):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {model._meta.db_table} SET fields_history=%s::jsonb[]", ([Jsonb({"foo": 42})],)
                )

    @pytest.mark.parametrize("model", FIELDS_HISTORY_MODELS_TO_TEST_PARAMS)
    def test_field_history_returning_fields(self, model):
        test_params = FIELDS_HISTORY_MODELS_TO_TEST_PARAMS[model]
        instance = test_params["factory"](**{test_params["test_field"]: test_params["initial"]})
        assert instance.fields_history == []

        setattr(instance, test_params["test_field"], test_params["update"])
        with triggers.fake_context():
            instance.save()
        # No need for refresh_from_db()
        assert len(instance.fields_history) == 1
        [field_update] = instance.fields_history
        assert field_update["before"] == {test_params["test_field"]: test_params["initial"]}
        assert field_update["after"] == {test_params["test_field"]: test_params["update"]}
