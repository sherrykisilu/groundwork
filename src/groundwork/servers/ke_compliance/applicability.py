"""Applicability logic over the synthetic obligation set.

Kept out of the server module so that the rule evaluation, which is the part with
edge cases, is directly unit testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .corpus import OBLIGATIONS, SECTORS, Obligation


class ComplianceError(ValueError):
    """Raised when a caller asks for something that does not exist or is malformed."""


@dataclass(frozen=True)
class BusinessProfile:
    """What we need to know about a business to decide what applies to it."""

    employees: int = 0
    annual_turnover_kes: int = 0
    sector: str = "services"
    handles_personal_data: bool = False
    has_physical_premises: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BusinessProfile:
        """Build a profile from loosely typed tool arguments."""
        if not isinstance(raw, dict):
            raise ComplianceError("profile must be an object")
        unknown = set(raw) - {
            "employees",
            "annual_turnover_kes",
            "sector",
            "handles_personal_data",
            "has_physical_premises",
        }
        if unknown:
            raise ComplianceError(
                f"unknown profile fields: {', '.join(sorted(unknown))}. "
                "Valid fields are employees, annual_turnover_kes, sector, "
                "handles_personal_data, has_physical_premises."
            )
        sector = str(raw.get("sector", "services")).lower().strip()
        if sector not in SECTORS:
            raise ComplianceError(
                f"unknown sector '{sector}'. Known sectors: {', '.join(SECTORS)}."
            )
        try:
            employees = int(raw.get("employees", 0))
            turnover = int(raw.get("annual_turnover_kes", 0))
        except (TypeError, ValueError) as exc:
            raise ComplianceError(
                "employees and annual_turnover_kes must be whole numbers"
            ) from exc
        if employees < 0 or turnover < 0:
            raise ComplianceError("employees and annual_turnover_kes cannot be negative")
        return cls(
            employees=employees,
            annual_turnover_kes=turnover,
            sector=sector,
            handles_personal_data=bool(raw.get("handles_personal_data", False)),
            has_physical_premises=bool(raw.get("has_physical_premises", False)),
        )

    def to_api(self) -> dict[str, Any]:
        return {
            "employees": self.employees,
            "annual_turnover_kes": self.annual_turnover_kes,
            "sector": self.sector,
            "handles_personal_data": self.handles_personal_data,
            "has_physical_premises": self.has_physical_premises,
        }


def _evaluate(rule: dict[str, Any], profile: BusinessProfile) -> tuple[bool, list[str]]:
    """Evaluate one rule against a profile, returning the verdict and the reasons."""
    if rule.get("always"):
        return True, ["applies to every registered business"]

    if "any_of" in rule:
        reasons: list[str] = []
        for branch in rule["any_of"]:
            matched, branch_reasons = _evaluate(branch, profile)
            if matched:
                return True, branch_reasons
            reasons.extend(branch_reasons)
        return False, reasons

    checks: list[tuple[bool, str]] = []
    if "min_employees" in rule:
        checks.append(
            (
                profile.employees >= rule["min_employees"],
                f"employees {profile.employees} vs minimum {rule['min_employees']}",
            )
        )
    if "min_turnover_kes" in rule:
        checks.append(
            (
                profile.annual_turnover_kes >= rule["min_turnover_kes"],
                (
                    f"turnover {profile.annual_turnover_kes:,} vs minimum "
                    f"{rule['min_turnover_kes']:,}"
                ),
            )
        )
    if "max_turnover_kes" in rule:
        checks.append(
            (
                profile.annual_turnover_kes <= rule["max_turnover_kes"],
                (
                    f"turnover {profile.annual_turnover_kes:,} vs maximum "
                    f"{rule['max_turnover_kes']:,}"
                ),
            )
        )
    if "handles_personal_data" in rule:
        checks.append(
            (
                profile.handles_personal_data == rule["handles_personal_data"],
                f"handles_personal_data is {profile.handles_personal_data}",
            )
        )
    if "has_physical_premises" in rule:
        checks.append(
            (
                profile.has_physical_premises == rule["has_physical_premises"],
                f"has_physical_premises is {profile.has_physical_premises}",
            )
        )
    if "sectors" in rule:
        checks.append(
            (
                profile.sector in rule["sectors"],
                f"sector '{profile.sector}' vs {', '.join(rule['sectors'])}",
            )
        )

    if not checks:
        return False, ["no rule conditions, treated as not applicable"]
    applies = all(passed for passed, _ in checks)
    return applies, [reason for _, reason in checks]


def applies(obligation: Obligation, profile: BusinessProfile) -> tuple[bool, list[str]]:
    """Whether one obligation applies to a profile, with the reasoning."""
    return _evaluate(obligation.rule, profile)


def check_applicability(profile: BusinessProfile) -> dict[str, Any]:
    """Split the obligation set into what applies and what does not, with reasons."""
    applicable: list[dict[str, Any]] = []
    not_applicable: list[dict[str, Any]] = []
    for obligation in OBLIGATIONS:
        matched, reasons = applies(obligation, profile)
        entry = obligation.to_api()
        entry["why"] = reasons
        (applicable if matched else not_applicable).append(entry)
    return {
        "profile": profile.to_api(),
        "applicable_count": len(applicable),
        "applicable": applicable,
        "not_applicable": not_applicable,
        "note": (
            "Applicability here is computed from the synthetic rules in this corpus "
            "only. It is not a legal opinion. Every item carries the citations it was "
            "derived from, so the reasoning can be checked against the source sections."
        ),
    }
