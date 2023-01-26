import random

from faker.providers import BaseProvider


class ItouProvider(BaseProvider):
    def asp_batch_filename(self) -> str:
        return f"RIAE_FS_{random.randint(0, 99999999999999)}.json"
