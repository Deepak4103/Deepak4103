"""Pure helpers: which periods of a day a leave scope covers."""
from decimal import Decimal

from django.conf import settings

FULL, FORENOON, AFTERNOON, PERIODS = "full", "forenoon", "afternoon", "periods"
SCOPE_CHOICES = [(FULL, "Full day"), (FORENOON, "Half day - forenoon"),
                 (AFTERNOON, "Half day - afternoon"), (PERIODS, "Specific periods")]


def parse_periods(csv):
    return {int(x) for x in str(csv or "").split(",") if x.strip().isdigit()}


def covered_periods(scope, periods_csv, forenoon_last, total=None):
    total = total or settings.PERIODS_PER_DAY
    allp = set(range(1, total + 1))
    if scope == FULL:
        return allp
    if scope == FORENOON:
        return {p for p in allp if p <= forenoon_last}
    if scope == AFTERNOON:
        return {p for p in allp if p > forenoon_last}
    return parse_periods(periods_csv) & allp


def day_value(scope):
    """Leave days deducted per calendar day: full = 1, half day or specific periods = 0.5."""
    return Decimal("1.0") if scope == FULL else Decimal("0.5")
