"""A synthetic compliance corpus for small businesses in Kenya.

Every document, section, figure, deadline and agency name below is INVENTED for this
project. Nothing here reproduces statutory text, and none of it is legal advice. The
numbers are deliberately round and labelled illustrative so that nobody mistakes them
for the real thresholds.

The point of this domain is not the content. It is to show that the same core, the
same skill format and the same evaluation harness work on a retrieval and citation
problem that has nothing in common with pipeline triage, and that the failure modes
you have to design against are completely different: here the agent invents an
obligation or answers without a citation, rather than stopping at the wrong root cause.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DISCLAIMER = (
    "SYNTHETIC DOCUMENT. This text was written for a software demonstration. It is "
    "not law, not legal advice, and not a reproduction of any real publication. "
    "Figures marked illustrative are invented."
)


@dataclass(frozen=True)
class Section:
    """One citable section of a document."""

    section_id: str
    heading: str
    text: str

    def to_api(self, doc_id: str) -> dict[str, Any]:
        return {
            "doc_id": doc_id,
            "section_id": self.section_id,
            "citation": f"{doc_id}#{self.section_id}",
            "heading": self.heading,
            "text": self.text,
            "disclaimer": DISCLAIMER,
        }


@dataclass(frozen=True)
class Document:
    """A synthetic guidance document."""

    doc_id: str
    title: str
    category: str
    agency: str
    sections: tuple[Section, ...]

    def to_api(self, *, include_text: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "doc_id": self.doc_id,
            "title": self.title,
            "category": self.category,
            "agency": self.agency,
            "disclaimer": DISCLAIMER,
            "sections": [{"section_id": s.section_id, "heading": s.heading} for s in self.sections],
        }
        if include_text:
            payload["sections"] = [s.to_api(self.doc_id) for s in self.sections]
        return payload


DOCUMENTS: tuple[Document, ...] = (
    Document(
        doc_id="DOC-DPA-01",
        title="Data protection registration and controller duties",
        category="data_protection",
        agency="Office of the Data Commissioner (synthetic stand in)",
        sections=(
            Section(
                "S1",
                "Who has to register as a data controller",
                "A business registers as a data controller when it decides why and how "
                "personal data is processed. In this synthetic model, registration is "
                "required when the business has an illustrative annual turnover above "
                "KES 5,000,000, or employs more than 10 people, or processes personal "
                "data as a core activity regardless of size. Processing customer names, "
                "phone numbers, national identification numbers or payment details "
                "counts as processing personal data. A sole trader who keeps only a "
                "paper sales book with no customer identifiers is outside scope in this "
                "model.",
            ),
            Section(
                "S2",
                "How registration works and what it costs",
                "Registration in this synthetic model is an online application listing "
                "the business details, the categories of personal data processed, the "
                "purposes, and a named contact. The illustrative fee is KES 4,000 for a "
                "small business and the certificate is valid for 24 months. Renewal is "
                "due 30 days before expiry. Changes to the categories of data processed "
                "are notified within 14 days.",
            ),
            Section(
                "S3",
                "Core duties of a data controller",
                "Collect only what is needed for a stated purpose. Tell people what you "
                "collect and why, in language they understand, at the point of "
                "collection. Keep personal data accurate and delete it when the purpose "
                "ends. Keep a written record of processing activities. Respond to a "
                "request from a person to access, correct or delete their data within an "
                "illustrative 30 days. Put a written agreement in place with any "
                "processor you share data with, such as a payroll bureau or a marketing "
                "platform.",
            ),
            Section(
                "S4",
                "Reporting a personal data breach",
                "A breach is any event where personal data is lost, exposed, altered or "
                "accessed without authorisation. In this synthetic model, a breach that "
                "presents a real risk of harm is reported to the regulator within 72 "
                "hours of becoming aware of it, and the affected people are told without "
                "undue delay. A breach with no real risk of harm is recorded in an "
                "internal log but not reported. Keep the internal log for an "
                "illustrative 5 years.",
            ),
        ),
    ),
    Document(
        doc_id="DOC-TAX-01",
        title="Business tax registration and the filing calendar",
        category="tax",
        agency="Revenue authority (synthetic stand in)",
        sections=(
            Section(
                "S1",
                "Annual income tax return",
                "Every registered business files an annual income tax return covering "
                "the previous calendar year. In this synthetic model the deadline is 30 "
                "June. A business that made no income still files a nil return. Keeping "
                "the supporting records for an illustrative 5 years is expected.",
            ),
            Section(
                "S2",
                "VAT registration and monthly returns",
                "A business registers for VAT once annual taxable turnover passes an "
                "illustrative KES 5,000,000, and may register voluntarily below that. "
                "Once registered, a VAT return is filed monthly by the 20th of the "
                "following month, including months with no sales. Deregistration is "
                "possible after an illustrative 12 consecutive months below the "
                "threshold.",
            ),
            Section(
                "S3",
                "Turnover tax for very small businesses",
                "A business with annual turnover below the illustrative KES 5,000,000 "
                "VAT threshold and above an illustrative KES 1,000,000 floor may pay "
                "turnover tax instead of ordinary income tax on business profit. In this "
                "synthetic model turnover tax is 3 percent of gross monthly sales, filed "
                "and paid monthly by the 20th. A business on turnover tax does not claim "
                "business expenses.",
            ),
            Section(
                "S4",
                "Late filing and late payment",
                "In this synthetic model a late return attracts a fixed illustrative "
                "penalty of KES 2,000 per month for a business, and late payment attracts "
                "illustrative interest of 1 percent per month on the unpaid amount. "
                "Penalties accrue from the day after the deadline, so filing a nil return "
                "on time is always cheaper than filing nothing.",
            ),
        ),
    ),
    Document(
        doc_id="DOC-PAY-01",
        title="Statutory payroll deductions for employers",
        category="payroll",
        agency="Revenue authority and statutory funds (synthetic stand in)",
        sections=(
            Section(
                "S1",
                "PAYE on employee salaries",
                "An employer with at least one employee on a salary deducts income tax "
                "from pay before it is paid out, and remits it. In this synthetic model "
                "PAYE is remitted by the 9th of the following month. The obligation "
                "starts with the first employee, including a single part time employee. "
                "A casual worker paid daily is still an employee for this purpose if the "
                "engagement runs beyond an illustrative 30 days.",
            ),
            Section(
                "S2",
                "Health insurance contributions",
                "Both the employer and the employee contribute to the statutory health "
                "fund. In this synthetic model the combined contribution is an "
                "illustrative 2.75 percent of gross pay, remitted monthly by the 9th. "
                "Registration with the fund happens before the first payroll run, not "
                "after it.",
            ),
            Section(
                "S3",
                "Pension contributions",
                "The statutory pension deduction in this synthetic model is 6 percent of "
                "pensionable pay from the employee, matched by 6 percent from the "
                "employer, remitted monthly by the 9th. There is an illustrative monthly "
                "cap of KES 2,160 on each side.",
            ),
            Section(
                "S4",
                "Housing levy",
                "In this synthetic model the housing levy is 1.5 percent of gross pay "
                "from the employee, matched by 1.5 percent from the employer, remitted "
                "monthly by the 9th alongside PAYE.",
            ),
            Section(
                "S5",
                "One monthly remittance date",
                "All four payroll obligations in this document share a single monthly "
                "deadline in this synthetic model: the 9th of the following month. "
                "Missing it attracts an illustrative penalty of 5 percent of the unpaid "
                "amount per fund. Keeping one payroll calendar reminder for the 9th "
                "covers PAYE, health, pension and housing together.",
            ),
        ),
    ),
    Document(
        doc_id="DOC-PERMIT-01",
        title="County business permits and premises licences",
        category="permits",
        agency="County government (synthetic stand in)",
        sections=(
            Section(
                "S1",
                "The single business permit",
                "A business operating from physical premises holds a single business "
                "permit from the county it trades in. In this synthetic model the permit "
                "is priced by premises size and activity, with an illustrative range of "
                "KES 5,000 to KES 50,000 a year for a small business. A business that is "
                "fully online with no premises open to the public and no signage is "
                "outside scope in this model.",
            ),
            Section(
                "S2",
                "Renewal and display",
                "The permit year runs with the calendar year in this synthetic model, "
                "and renewal is due by 31 March. The permit is displayed at the premises. "
                "Trading on an expired permit attracts an illustrative penalty of 10 "
                "percent of the permit fee per month.",
            ),
            Section(
                "S3",
                "Food handling certificates",
                "A business that prepares, serves or sells food holds a food hygiene "
                "licence for the premises and a health certificate for each person who "
                "handles food. In this synthetic model health certificates are renewed "
                "every 6 months and the premises licence annually. A packaged goods "
                "retailer that does not open, prepare or serve food needs the premises "
                "licence only.",
            ),
        ),
    ),
    Document(
        doc_id="DOC-EMP-01",
        title="Employment contracts and records",
        category="employment",
        agency="Labour ministry (synthetic stand in)",
        sections=(
            Section(
                "S1",
                "Written contracts",
                "An employee engaged for more than an illustrative 3 months gets a "
                "written contract stating the role, pay, hours, leave and notice period. "
                "In this synthetic model the employer keeps a signed copy and gives the "
                "employee one.",
            ),
            Section(
                "S2",
                "Records to keep",
                "Keep, for each employee: the contract, a pay record showing gross pay "
                "and each deduction, leave taken, and any disciplinary record. In this "
                "synthetic model these are kept for 5 years after the employment ends. "
                "Pay records overlap heavily with what the payroll obligations in "
                "DOC-PAY-01 already require, so one payroll system usually satisfies both.",
            ),
            Section(
                "S3",
                "Employee personal data",
                "Employee records are personal data. The duties in DOC-DPA-01 section S3 "
                "apply to them, including the duty to keep them accurate and to delete "
                "them when the retention period ends. An employer that is otherwise below "
                "the data controller registration thresholds does not usually cross them "
                "by holding employee records alone, in this synthetic model.",
            ),
        ),
    ),
    Document(
        doc_id="DOC-SECTOR-01",
        title="Sector specific notes",
        category="sector",
        agency="Various (synthetic stand in)",
        sections=(
            Section(
                "S1",
                "Food and beverage",
                "In addition to the general permits, a food business in this synthetic "
                "model holds a food hygiene licence (see DOC-PERMIT-01 section S3), keeps "
                "a supplier traceability record for an illustrative 12 months, and "
                "displays allergen information where food is sold prepared.",
            ),
            Section(
                "S2",
                "Financial services and fintech",
                "A business that holds client money, lends, or moves funds on behalf of "
                "others needs a sector licence in this synthetic model, in addition to "
                "everything in DOC-TAX-01 and DOC-DPA-01. Processing payment card data "
                "makes a business a data controller as a core activity, so the DOC-DPA-01 "
                "section S1 size thresholds do not get you out of registering.",
            ),
            Section(
                "S3",
                "Health and wellness",
                "A business providing clinical or diagnostic services needs a facility "
                "licence and individually licensed practitioners in this synthetic model. "
                "Health data is sensitive personal data, so the DOC-DPA-01 duties apply "
                "from the first client regardless of turnover or headcount.",
            ),
        ),
    ),
)

DOCUMENTS_BY_ID: dict[str, Document] = {doc.doc_id: doc for doc in DOCUMENTS}


@dataclass(frozen=True)
class Obligation:
    """A structured obligation, with the rule that decides whether it applies."""

    obligation_id: str
    title: str
    category: str
    agency: str
    frequency: str
    deadline: str
    citations: tuple[str, ...]
    rule: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def to_api(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "title": self.title,
            "category": self.category,
            "agency": self.agency,
            "frequency": self.frequency,
            "deadline": self.deadline,
            "citations": list(self.citations),
            "applies_when": self.rationale,
            "disclaimer": DISCLAIMER,
        }


OBLIGATIONS: tuple[Obligation, ...] = (
    Obligation(
        "OB-TAX-INCOME",
        "File an annual income tax return",
        "tax",
        "Revenue authority (synthetic stand in)",
        "annual",
        "30 June",
        ("DOC-TAX-01#S1",),
        {"always": True},
        "Every registered business, including one that made no income.",
    ),
    Obligation(
        "OB-TAX-VAT",
        "Register for VAT and file monthly VAT returns",
        "tax",
        "Revenue authority (synthetic stand in)",
        "monthly",
        "20th of the following month",
        ("DOC-TAX-01#S2",),
        {"min_turnover_kes": 5_000_000},
        "Annual taxable turnover above the illustrative KES 5,000,000 threshold.",
    ),
    Obligation(
        "OB-TAX-TOT",
        "File and pay turnover tax",
        "tax",
        "Revenue authority (synthetic stand in)",
        "monthly",
        "20th of the following month",
        ("DOC-TAX-01#S3",),
        {"min_turnover_kes": 1_000_000, "max_turnover_kes": 4_999_999},
        "Turnover between the illustrative KES 1,000,000 floor and the VAT threshold.",
    ),
    Obligation(
        "OB-PAY-PAYE",
        "Deduct and remit PAYE",
        "payroll",
        "Revenue authority (synthetic stand in)",
        "monthly",
        "9th of the following month",
        ("DOC-PAY-01#S1", "DOC-PAY-01#S5"),
        {"min_employees": 1},
        "One or more employees on a salary, including part time.",
    ),
    Obligation(
        "OB-PAY-HEALTH",
        "Remit statutory health insurance contributions",
        "payroll",
        "Statutory health fund (synthetic stand in)",
        "monthly",
        "9th of the following month",
        ("DOC-PAY-01#S2", "DOC-PAY-01#S5"),
        {"min_employees": 1},
        "One or more employees.",
    ),
    Obligation(
        "OB-PAY-PENSION",
        "Remit statutory pension contributions",
        "payroll",
        "Statutory pension fund (synthetic stand in)",
        "monthly",
        "9th of the following month",
        ("DOC-PAY-01#S3", "DOC-PAY-01#S5"),
        {"min_employees": 1},
        "One or more employees.",
    ),
    Obligation(
        "OB-PAY-HOUSING",
        "Remit the housing levy",
        "payroll",
        "Statutory housing fund (synthetic stand in)",
        "monthly",
        "9th of the following month",
        ("DOC-PAY-01#S4", "DOC-PAY-01#S5"),
        {"min_employees": 1},
        "One or more employees.",
    ),
    Obligation(
        "OB-DPA-REGISTER",
        "Register as a data controller",
        "data_protection",
        "Office of the Data Commissioner (synthetic stand in)",
        "every 24 months",
        "30 days before certificate expiry",
        ("DOC-DPA-01#S1", "DOC-DPA-01#S2"),
        {
            "any_of": [
                {"min_turnover_kes": 5_000_000},
                {"min_employees": 11},
                {"sectors": ["fintech", "health"], "handles_personal_data": True},
            ]
        },
        "Turnover above the illustrative threshold, more than 10 employees, or "
        "processing personal data as a core activity.",
    ),
    Obligation(
        "OB-DPA-DUTIES",
        "Meet data controller duties and handle data subject requests",
        "data_protection",
        "Office of the Data Commissioner (synthetic stand in)",
        "ongoing",
        "30 days to answer a data subject request",
        ("DOC-DPA-01#S3", "DOC-DPA-01#S4"),
        {"handles_personal_data": True},
        "Any business processing personal data, whether or not it has to register.",
    ),
    Obligation(
        "OB-PERMIT-SBP",
        "Hold and renew a single business permit",
        "permits",
        "County government (synthetic stand in)",
        "annual",
        "31 March",
        ("DOC-PERMIT-01#S1", "DOC-PERMIT-01#S2"),
        {"has_physical_premises": True},
        "Trading from physical premises in a county.",
    ),
    Obligation(
        "OB-PERMIT-FOOD",
        "Hold a food hygiene licence and food handler certificates",
        "permits",
        "County government (synthetic stand in)",
        "licence annual, certificates every 6 months",
        "on expiry",
        ("DOC-PERMIT-01#S3", "DOC-SECTOR-01#S1"),
        {"sectors": ["food"], "has_physical_premises": True},
        "Preparing, serving or selling open food from premises.",
    ),
    Obligation(
        "OB-EMP-CONTRACT",
        "Issue written contracts and keep employment records",
        "employment",
        "Labour ministry (synthetic stand in)",
        "ongoing",
        "contract within 3 months of engagement",
        ("DOC-EMP-01#S1", "DOC-EMP-01#S2"),
        {"min_employees": 1},
        "One or more employees engaged for more than the illustrative 3 month mark.",
    ),
    Obligation(
        "OB-SECTOR-FINLICENCE",
        "Hold a financial services licence",
        "sector",
        "Financial regulator (synthetic stand in)",
        "annual",
        "on renewal date",
        ("DOC-SECTOR-01#S2",),
        {"sectors": ["fintech"]},
        "Holding client money, lending, or moving funds for others.",
    ),
)

OBLIGATIONS_BY_ID: dict[str, Obligation] = {ob.obligation_id: ob for ob in OBLIGATIONS}

CATEGORIES: tuple[str, ...] = tuple(sorted({ob.category for ob in OBLIGATIONS}))
SECTORS: tuple[str, ...] = ("retail", "food", "services", "fintech", "health", "manufacturing")


def all_sections() -> list[tuple[str, Section]]:
    """Every (doc_id, section) pair, in document order."""
    return [(doc.doc_id, section) for doc in DOCUMENTS for section in doc.sections]
