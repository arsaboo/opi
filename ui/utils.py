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
}

# Fields that should right-justify even when the value is non-numeric
RIGHT_JUSTIFY_FIELDS = {
    # Roll short options
    "Current Strike",
    "DTE",
    "Underlying Price",
    "Quantity",
    "New Strike",
    "Roll Out (Days)",
    "Credit",
    "Cr/Day",
    "CrDayPerPt",
    "Extrinsic",
    "Strike Δ",
    "Strike \u0010",
    # Spreads and margin screens
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


def style_cell(field: str, value: Any, prev: Any | None = None) -> Text:
    style = ""
    text = "" if value is None else str(value)

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

    # Credit-like positive/negative coloring
    if field in {"Credit", "Cr/Day", "CrDayPerPt"}:
        v = _to_float(value)
        if v is not None:
            if v > 0:
                style = "green"
            elif v < 0:
                style = "red"
            pv = _to_float(prev)
            if pv is not None:
                if v > pv:
                    style = "bold green"
                elif v < pv:
                    style = "bold red"
        return Text(text, style=style, justify="right")

    if field in {"Strike Δ", "Strike \u0010"}:  # include any prior encoding artifacts
        v = _to_float(value)
        if v is not None:
            if v > 0:
                style = "green"
            elif v < 0:
                style = "red"
        return Text(text, style=style, justify="right")

    # Extrinsic heuristic
    if field == "Extrinsic":
        v = _to_float(value)
        if v is not None:
            style = "green" if v < 1 else "red"
        return Text(text, style=style, justify="right")

    # Percent fields formatting and delta coloring
    if field in PERCENT_FIELDS:
        v = _to_float(value)
        pv = _to_float(prev)
        # Heuristic: if looks like a fraction (< 1) but not obviously a percent string, convert to percent
        display = text
        if v is not None:
            if "%" in str(value):
                display = str(value)
            else:
                # If value likely a fraction, scale by 100 for display
                display = _fmt_percent(v * 100 if 0 <= v <= 1 else v)
        if v is not None and pv is not None:
            if v > pv:
                style = "bold green"
            elif v < pv:
                style = "bold red"
        # Base color for positive/negative
        if not style and v is not None:
            style = "green" if v > 0 else "red" if v < 0 else ""
        return Text(display, style=style, justify="right")

    # Money fields formatting
    if field in MONEY_FIELDS:
        v = _to_float(value)
        pv = _to_float(prev)
        display = _fmt_money(v) if v is not None else text
        if v is not None and pv is not None:
            if v > pv:
                style = "bold red"
            elif v < pv:
                style = "bold green"
        return Text(display, style=style, justify="right")

    # Default numeric handling
    v = _to_float(value)
    if v is not None:
        pv = _to_float(prev)
        if pv is not None:
            if v > pv:
                style = "bold"
            elif v < pv:
                style = "bold"
        return Text(f"{v}", style=style, justify="right")

    # If value is non-numeric but column is numeric-like, keep right alignment
    if field in RIGHT_JUSTIFY_FIELDS:
        return Text(text, style=style, justify="right")

    # Fallback
    return Text(text, style=style, justify="left")
