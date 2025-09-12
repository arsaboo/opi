from rich.text import Text
from typing import Any, Optional


PERCENT_FIELDS = {
    "cagr",
    "ann_rom",
    "mid_annualized_return",
    "nat_annualized_return",
    "ann_cost_return",
    "protection",
}

# Percent value scaling rules:
# - Fields in FRACTION_PERCENT_FIELDS are provided as fractions (0..1) and
#   should be multiplied by 100 for display.
# - All other fields in PERCENT_FIELDS are already provided as true percent
#   values (e.g., 2.49 for 2.49%) and should NOT be scaled again.
FRACTION_PERCENT_FIELDS = {"cagr", "protection", "ann_rom"}

MONEY_FIELDS = {
    "investment",
    "borrowed",
    "repayment",
    "repayment_sell",
    "mid_upfront_amount",
    "mid_investment",
    "mid_borrowed",
    "nat_upfront_amount",
    "nat_investment",
    "nat_borrowed",
    "face_value",
    "margin",
    # Roll short options P/L values
    "P/L Day",
    "P/L Open",
}

# Fields that should right-justify even when the value is non-numeric
RIGHT_JUSTIFY_FIELDS = {
    # Roll short options
    "Current Strike",
    "DTE",
    "Underlying Price",
    "Underlying",
    "Quantity",
    "Qty",
    "New Strike",
    "Roll Out (Days)",
    "Credit",
    "Cr/Day",
    "CrDayPerPt",
    "Extrinsic",
    "Strike Δ",
    "Strike \u0010",
    "strike_low",
    "strike_high",
    "low_strike",
    "high_strike",
    "investment",
    "price",
    "max_profit",
    "cagr",
    "protection",
    "margin_req",
    "ann_rom",
    "days_to_expiry",
    "net_price",
    "mid_net_price",
    "nat_net_price",
    "face_value",
    "count",
    "strike",
    "margin",
}


def _to_float(val: Any) -> Optional[float]:
    try:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(",", "")
        s = s.replace("$", "").replace("%", "")
        return float(s) if s != "" else None
    except Exception:
        return None


def _fmt_money(val: float) -> str:
    return f"${val:,.2f}"


def _fmt_percent(val: float) -> str:
    return f"{val:.2f}%"


def style_flags(text: str) -> Text:
    return Text(text or "", style=("bold red" if text else ""), justify="left")


def style_ba(
    bid: Optional[float],
    ask: Optional[float],
    prev_bid: Optional[float] = None,
    prev_ask: Optional[float] = None,
) -> Text:
    bid_style = ""
    ask_style = ""
    try:
        if bid is not None and prev_bid is not None:
            if float(bid) > float(prev_bid):
                bid_style = "green"
            elif float(bid) < float(prev_bid):
                bid_style = "red"
    except Exception:
        pass
    try:
        if ask is not None and prev_ask is not None:
            if float(ask) < float(prev_ask):
                ask_style = "green"
            elif float(ask) > float(prev_ask):
                ask_style = "red"
    except Exception:
        pass
    t = Text()
    t.append(f"{float(bid):.2f}" if bid is not None else "", style=bid_style)
    t.append("|")
    t.append(f"{float(ask):.2f}" if ask is not None else "", style=ask_style)
    return t


def _get_delta_style(
    v: Optional[float], pv: Optional[float], higher_is_better: bool = True
) -> str:
    if v is None or pv is None:
        return ""
    if v > pv:
        return "bold green" if higher_is_better else "bold red"
    if v < pv:
        return "bold red" if higher_is_better else "bold green"
    return ""


def style_cell(field: str, value: Any, prev: Any | None = None) -> Text:
    style = ""
    text = "" if value is None else str(value)
    justify = "left"

    # Status-like fields
    if field.lower() in {"status"}:
        val = (text or "").strip()
        if val == "OTM":
            style = "green"
        elif val in {"ITM", "Deep ITM"}:
            style = "red"
        elif val == "Just ITM":
            style = "yellow"
        return Text(val, style=style, justify="left")

    if field.lower() in {"config status", "config_status"} and text == "Not Configured":
        return Text(text, style="yellow", justify="left")

    v = _to_float(value)
    pv = _to_float(prev)
    display = text
    is_numeric = v is not None

    if is_numeric:
        justify = "right"

        # Credit-like positive/negative coloring
        if field in {"Credit", "Cr/Day", "CrDayPerPt"}:
            style = _get_delta_style(v, pv)
            if not style and v is not None:
                if v > 0:
                    style = "green"
                elif v < 0:
                    style = "red"

        # Strike delta
        elif field in {"Strike Δ", "Strike \u0010"}:
            if v is not None:
                if v > 0:
                    style = "green"
                elif v < 0:
                    style = "red"

        # Extrinsic heuristic
        elif field == "Extrinsic":
            if v is not None:
                style = "green" if v < 1 else "red"

        # Percent fields formatting and delta coloring
        elif field in PERCENT_FIELDS:
            style = _get_delta_style(v, pv)
            if "%" in text:
                display = text
            elif v is not None:
                # Convert only fraction-based fields; others are already percent values
                if field in FRACTION_PERCENT_FIELDS and 0 <= v <= 1:
                    display = _fmt_percent(v * 100)
                else:
                    display = _fmt_percent(v)

            if not style and v is not None:
                style = "green" if v > 0 else "red" if v < 0 else ""

        # Money fields formatting (generic)
        elif field in MONEY_FIELDS:
            # Special handling for P/L fields: color by sign
            if field in {"P/L Day", "P/L Open"}:
                if v is not None:
                    display = _fmt_money(v)
                    # Base style by sign
                    if v > 0:
                        style = "green"
                    elif v < 0:
                        style = "red"
                    # Emphasize if changed
                    if pv is not None and v != pv:
                        style = f"bold {style}".strip()
                else:
                    display = text
            else:
                style = _get_delta_style(v, pv, higher_is_better=False)
                if v is not None:
                    display = _fmt_money(v)

        # Underlying Price
        elif field in {"Underlying Price", "Underlying"}:
            style = _get_delta_style(v, pv)
            if isinstance(v, float):
                display = f"{v:.2f}"

        # Default numeric handling
        else:
            if pv is not None:
                if v > pv or v < pv:
                    style = "bold"
            display = f"{v}"

    # If value is non-numeric but column is numeric-like, keep right alignment
    if not is_numeric and field in RIGHT_JUSTIFY_FIELDS:
        justify = "right"

    # Fallback
    return Text(display, style=style, justify=justify)
