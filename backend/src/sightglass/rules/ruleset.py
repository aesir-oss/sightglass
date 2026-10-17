"""The full rule set. Importing this module registers every rule on :data:`RULES`."""

from sightglass.rules import behavior, build, dependencies, hooks, patterns, provenance, source, timing
from sightglass.rules.base import RULES

__all__ = ["RULES", "behavior", "build", "dependencies", "hooks", "patterns", "provenance", "source", "timing"]
