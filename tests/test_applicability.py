"""Tests for the applicability rule engine."""

from __future__ import annotations

import pytest

from groundwork.servers.ke_compliance.applicability import (
    BusinessProfile,
    ComplianceError,
    check_applicability,
)

SOLE_TRADER = {
    "employees": 0,
    "annual_turnover_kes": 400_000,
    "sector": "services",
    "handles_personal_data": False,
    "has_physical_premises": False,
}


def profile(**overrides: object) -> BusinessProfile:
    return BusinessProfile.from_dict({**SOLE_TRADER, **overrides})


def applicable_ids(p: BusinessProfile) -> set[str]:
    return {item["obligation_id"] for item in check_applicability(p)["applicable"]}


class TestProfileParsing:
    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ComplianceError, match="unknown"):
            BusinessProfile.from_dict({**SOLE_TRADER, "favourite_colour": "blue"})

    def test_unknown_sector_lists_the_valid_ones(self) -> None:
        with pytest.raises(ComplianceError, match="retail"):
            profile(sector="aerospace")

    def test_negative_numbers_are_rejected(self) -> None:
        with pytest.raises(ComplianceError):
            profile(employees=-1)

    def test_round_trips_to_api_form(self) -> None:
        assert profile(employees=3).to_api()["employees"] == 3


class TestRules:
    def test_everyone_files_an_annual_return(self) -> None:
        assert "OB-TAX-INCOME" in applicable_ids(profile())

    def test_no_employees_means_no_payroll_obligations(self) -> None:
        ids = applicable_ids(profile())
        assert not {i for i in ids if i.startswith("OB-PAY-")}

    def test_one_employee_triggers_all_four_payroll_remittances(self) -> None:
        ids = applicable_ids(profile(employees=1))
        assert {"OB-PAY-PAYE", "OB-PAY-HEALTH", "OB-PAY-PENSION", "OB-PAY-HOUSING"} <= ids

    def test_turnover_bands_are_mutually_exclusive(self) -> None:
        below = applicable_ids(profile(annual_turnover_kes=800_000))
        middle = applicable_ids(profile(annual_turnover_kes=3_200_000))
        above = applicable_ids(profile(annual_turnover_kes=9_000_000))
        assert "OB-TAX-TOT" not in below and "OB-TAX-VAT" not in below
        assert "OB-TAX-TOT" in middle and "OB-TAX-VAT" not in middle
        assert "OB-TAX-VAT" in above and "OB-TAX-TOT" not in above

    def test_data_duties_apply_without_registration(self) -> None:
        ids = applicable_ids(profile(handles_personal_data=True))
        assert "OB-DPA-DUTIES" in ids
        assert "OB-DPA-REGISTER" not in ids

    def test_registration_triggers_on_headcount(self) -> None:
        ids = applicable_ids(profile(employees=14, handles_personal_data=True))
        assert "OB-DPA-REGISTER" in ids

    def test_permits_need_premises(self) -> None:
        assert "OB-PERMIT-SBP" not in applicable_ids(profile())
        assert "OB-PERMIT-SBP" in applicable_ids(profile(has_physical_premises=True))

    def test_food_licence_needs_both_sector_and_premises(self) -> None:
        assert "OB-PERMIT-FOOD" not in applicable_ids(profile(sector="food"))
        assert "OB-PERMIT-FOOD" in applicable_ids(
            profile(sector="food", has_physical_premises=True)
        )

    def test_fintech_licence_is_sector_gated(self) -> None:
        assert "OB-SECTOR-FINLICENCE" in applicable_ids(profile(sector="fintech"))
        assert "OB-SECTOR-FINLICENCE" not in applicable_ids(profile(sector="retail"))


class TestOutputShape:
    def test_every_obligation_is_classified_exactly_once(self) -> None:
        result = check_applicability(profile(employees=4))
        ids = [item["obligation_id"] for item in result["applicable"] + result["not_applicable"]]
        assert len(ids) == len(set(ids))
        assert result["applicable_count"] == len(result["applicable"])

    def test_every_entry_carries_reasons_and_citations(self) -> None:
        result = check_applicability(profile(employees=4, has_physical_premises=True))
        for item in result["applicable"]:
            assert item["why"], item["obligation_id"]
            assert item["citations"], item["obligation_id"]

    def test_reasons_quote_the_threshold_that_decided_it(self) -> None:
        result = check_applicability(profile(annual_turnover_kes=3_200_000))
        tot = next(i for i in result["applicable"] if i["obligation_id"] == "OB-TAX-TOT")
        assert any("1,000,000" in reason for reason in tot["why"])

    def test_payload_is_labelled_as_synthetic(self) -> None:
        result = check_applicability(profile())
        assert "not a legal opinion" in result["note"]
        assert "SYNTHETIC" in result["applicable"][0]["disclaimer"]
