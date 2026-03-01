"""Lightweight enums for stable naming in interfaces and diagnostics."""

from __future__ import annotations

from enum import Enum


class Region(str, Enum):
    EU27 = "EU27"
    CHINA = "China"
    ROW = "RoW"


class Material(str, Enum):
    TIN = "tin"
    ZINC = "zinc"
    NICKEL = "nickel"


__all__ = ["Region", "Material"]
