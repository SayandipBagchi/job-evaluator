"""Lever adapter: stubbed for P3 behind the same interface.

Every method raises `not_implemented` so the skill reports the gap plainly
instead of guessing. The confirm rule is enforced even in the stub.
"""

from __future__ import annotations

from .base import AtsAdapter, AtsError, ConfirmationRequired


class LeverAdapter(AtsAdapter):
    name = "lever"

    def __init__(self, *_, **__):
        pass

    def _todo(self):
        raise AtsError("not_implemented", "The Lever adapter is planned for P3. Attach resumes or export a CSV for now.")

    def list_jobs(self, status: str = "open") -> list[dict]:
        self._todo()

    def list_applicants(self, job_id: str, page: int = 1, per_page: int = 100) -> dict:
        self._todo()

    def get_resume(self, application_id: str, dest_dir: str) -> str:
        self._todo()

    def add_note(self, application_id: str, text: str, confirm: bool, on_behalf_of: str | None = None) -> dict:
        if not confirm:
            raise ConfirmationRequired({"application_id": application_id, "note": text})
        self._todo()
