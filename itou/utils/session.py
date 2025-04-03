import json
import uuid

import itou.utils.json
from itou.utils import python


class SessionNamespace:
    """Class to facilitate the usage of namespaces inside the session."""

    NOT_SET = python.Sentinel()

    def __init__(self, session, namespace):
        self._session = session
        self.name = str(namespace)

    def __repr__(self):
        return f"<SessionNamespace({self._session[self.name]!r})>"

    def __contains__(self, item):
        return item in self._session[self.name]

    def init(self, data):
        self._session[self.name] = data
        self._session.modified = True

    def get(self, key, default=NOT_SET):
        return self._session[self.name].get(key, default)

    def set(self, key, value):
        self._session[self.name][key] = value
        self._session.modified = True

    def update(self, data):
        self._session[self.name].update(data)
        self._session.modified = True

    def exists(self):
        return self.name in self._session

    def delete(self):
        if not self.exists():
            return

        del self._session[self.name]
        self._session.modified = True

    def save(self):
        self._session.save()

    def as_dict(self):
        return dict(self._session[self.name])

    @classmethod
    def create_uuid_namespace(cls, session, data=None):
        s = cls(session, namespace=str(uuid.uuid4()))
        if data is None:
            data = {}
        s.init(data)
        return s


class JSONSerializer:
    """Class to be used in SESSION_SERIALIZER, so we can serialize data using our custom JSON encoder/decoder."""

    def dumps(self, obj):
        # Using latin-1 like django.contrib.sessions.serializers.JSONSerializer
        return json.dumps(obj, cls=itou.utils.json.JSONEncoder).encode("latin-1")

    def loads(self, data):
        # Using latin-1 like django.contrib.sessions.serializers.JSONSerializer
        return json.loads(data.decode("latin-1"), cls=itou.utils.json.JSONDecoder)
