"""The adapter interface. Reads are free; every write takes `confirm` and refuses without it (GR12)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AtsError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ConfirmationRequired(Exception):
    def __init__(self, preview: dict):
        super().__init__("confirmation_required")
        self.preview = preview


class AtsAdapter(ABC):
    name = "base"

    @abstractmethod
    def list_jobs(self, status: str = "open") -> list[dict]:
        """Jobs with id, name, status. No candidate data."""

    @abstractmethod
    def list_applicants(self, job_id: str, page: int = 1, per_page: int = 100) -> dict:
        """One page of applications: application_id, candidate_id, stage, has_resume, profile_url. No contact details."""

    @abstractmethod
    def get_resume(self, application_id: str, dest_dir: str) -> str:
        """Download the resume attachment for an application and return the local path."""

    @abstractmethod
    def add_note(self, application_id: str, text: str, confirm: bool, on_behalf_of: str | None = None) -> dict:
        """Write a note to the candidate's record. Raises ConfirmationRequired unless confirm is True."""
