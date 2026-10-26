"""ATS adapters. Every adapter implements AtsAdapter; Greenhouse is the reference."""

from .base import AtsAdapter, AtsError, ConfirmationRequired
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter

ADAPTERS = {"greenhouse": GreenhouseAdapter, "lever": LeverAdapter}

__all__ = ["ADAPTERS", "AtsAdapter", "AtsError", "ConfirmationRequired", "GreenhouseAdapter", "LeverAdapter"]
