"""The full rule set. Importing this module registers every rule on :data:`RULES`."""

from sightglass.rules import provenance, source
from sightglass.rules.base import RULES

__all__ = ["RULES", "provenance", "source"]
