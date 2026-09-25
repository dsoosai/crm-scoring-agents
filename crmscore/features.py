"""Feature contracts. One per CRM object. The contract is the schema gate."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class FeatureSpec:
    object: str            # "account" or "lead"
    id_col: str
    name_col: str
    label: str
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    period_freq: str       # "Q" or "M"
    labels: dict = field(default_factory=dict)  # human labels for reasons

    @property
    def features(self) -> list[str]:
        return list(self.numeric) + list(self.categorical)

    def validate(self, df: pd.DataFrame) -> list[str]:
        """Return a list of contract violations (empty list means OK)."""
        problems = []
        for col in [self.id_col, "period", *self.features]:
            if col not in df.columns:
                problems.append(f"missing column: {col}")
        for col in self.numeric:
            if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
                problems.append(f"non-numeric column: {col}")
        return problems


ACCOUNT = FeatureSpec(
    object="account",
    id_col="account_id",
    name_col="account_name",
    label="expanded_next_q",
    numeric=("employees", "sales", "revenue", "profit", "transactions", "product_usage_pct",
             "support_tickets", "csat", "days_since_last_activity", "open_opps"),
    categorical=("industry", "department"),
    period_freq="Q",
    labels={
        "employees": "Employees", "sales": "Sales", "revenue": "Revenue", "profit": "Profit",
        "transactions": "Transactions", "product_usage_pct": "Product usage %",
        "support_tickets": "Support tickets", "csat": "CSAT",
        "days_since_last_activity": "Days since last activity", "open_opps": "Open opportunities",
        "industry": "Industry", "department": "Consuming department",
    },
)

LEAD = FeatureSpec(
    object="lead",
    id_col="lead_id",
    name_col="company",
    label="converted_30d",
    numeric=("site_visits", "email_opens", "company_size", "days_to_first_touch"),
    categorical=("industry", "role", "keyword", "lead_source"),
    period_freq="M",
    labels={
        "site_visits": "Site visits", "email_opens": "Email opens", "company_size": "Company size",
        "days_to_first_touch": "Days to first touch", "industry": "Industry", "role": "Role",
        "keyword": "Search keyword", "lead_source": "Lead source",
    },
)

SPECS = {"account": ACCOUNT, "lead": LEAD}


def spec_for(obj: str) -> FeatureSpec:
    try:
        return SPECS[obj]
    except KeyError as exc:
        raise ValueError(f"unknown object '{obj}', expected one of {list(SPECS)}") from exc


def shift_period(period: str, freq: str, n: int) -> str:
    return str(pd.Period(period, freq=freq) + n)


def period_range(start: str, end: str, freq: str) -> list[str]:
    return [str(p) for p in pd.period_range(pd.Period(start, freq=freq), pd.Period(end, freq=freq), freq=freq)]
