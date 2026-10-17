"""Sightglass: see what a package release actually ships."""

from importlib.metadata import version

__version__ = version("sightglass")

__all__ = ["__version__"]
