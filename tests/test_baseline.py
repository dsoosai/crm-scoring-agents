import pandas as pd

from crmscore.baseline import lead_score_v0


def test_v0_lead_score_ignores_categories():
    """The notebook weights every one-hot column equally, so categories add a constant."""
    df = pd.DataFrame({
        "site_visits": [10, 10],
        "industry": ["Technology", "Retail"],
        "role": ["Decision Maker", "Gatekeeper"],
        "keyword": ["CRM", "Security"],
    })
    s = lead_score_v0(df)
    assert s[0] == s[1]
