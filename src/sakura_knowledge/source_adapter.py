"""Explicit adapter boundary: frozen input facts to existing contract records."""
from typing import Protocol


class SourceAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def input_inventory(self, path): ...
    def inspect(self, path): ...
    def iter_records(self, path): ...
    def source_metadata(self, path) -> dict | list[dict]:
        """One owner or an ordered owner list; records explicitly identify their source."""
        ...
