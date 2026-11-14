"""Persian text normalization, literal 'null' guard, JSON parsers, and indoor mall regex extraction."""

import json
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# Character translation table: Arabic Yeh/Kaf & Eastern/Persian digits -> normalized Persian + ASCII digits
_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ئ": "ی",
        "ك": "ک",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "\u200c": " ",  # ZWNJ -> space for uniform token matching
        "\u200f": "",
        "\u200e": "",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)

_ASCII_TO_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

_MULTI_SPACE_RE = re.compile(r"\s+")

# Indoor Mall Micro-Navigation regexes over Persian addresses
_MALL_RE = re.compile(
    r"(پاساژ|مجتمع\s+تجاری|مجتمع|مرکز\s+خرید|بازار)\s+([^،,\n\-]+)",
    flags=re.UNICODE,
)
_FLOOR_RE = re.compile(
    r"(طبقه\s*(?:همکف|زیرهمکف|منفی\s*[0-9۰-۹یکدو]+|[0-9۰-۹+\-]+|اول|دوم|سوم|چهارم|پنجم|ششم|هفتم))",
    flags=re.UNICODE,
)
_UNIT_RE = re.compile(
    r"((?:واحد|پلاک|غرفه)\s*[0-9۰-۹A-Za-z/\-]+)",
    flags=re.UNICODE,
)


def clean_null_str(val: str | None) -> str | None:
    """Convert literal `'null'`, `'None'`, or empty whitespace strings from CSVs into Python `None`."""
    if val is None:
        return None
    stripped = val.strip()
    if not stripped or stripped.lower() in ("null", "none", "nan"):
        return None
    return stripped


def normalize_persian_text(text: str | None) -> str:
    """Normalize Persian/Arabic characters, convert digits to ASCII, and collapse whitespace for search."""
    cleaned = clean_null_str(text)
    if not cleaned:
        return ""
    translated = cleaned.translate(_CHAR_MAP).lower()
    return _MULTI_SPACE_RE.sub(" ", translated).strip()


def to_persian_digits(val: str | int | float) -> str:
    """Format ASCII digits into Persian digits (`۰`..`۹`)."""
    return str(val).translate(_ASCII_TO_FA_DIGITS)


def extract_mall_micro_guide(address: str | None) -> dict[str, str | None]:
    """Extract structured indoor mall coordinates (`mall_name`, `floor_label`, `unit_label`, `note_fa`)."""
    cleaned = clean_null_str(address)
    if not cleaned:
        return {"mall_name": None, "floor_label": None, "unit_label": None, "note_fa": None}

    mall_name: str | None = None
    floor_label: str | None = None
    unit_label: str | None = None

    mall_match = _MALL_RE.search(cleaned)
    if mall_match:
        prefix = _MULTI_SPACE_RE.sub(" ", mall_match.group(1)).strip()
        name_part = mall_match.group(2).strip()
        # Trim trailing floor/unit words if they weren't comma-separated
        name_part = re.split(r"\b(?:طبقه|واحد|پلاک|غرفه)\b", name_part)[0].strip()
        if name_part:
            mall_name = f"{prefix} {name_part}"

    floor_match = _FLOOR_RE.search(cleaned)
    if floor_match:
        floor_label = _MULTI_SPACE_RE.sub(" ", floor_match.group(1)).strip()

    unit_match = _UNIT_RE.search(cleaned)
    if unit_match:
        unit_label = _MULTI_SPACE_RE.sub(" ", unit_match.group(1)).strip()

    parts = [p for p in (mall_name, floor_label, unit_label) if p]
    note_fa = "، ".join(parts) if parts else None

    return {
        "mall_name": mall_name,
        "floor_label": floor_label,
        "unit_label": unit_label,
        "note_fa": note_fa,
    }


def safe_json_loads(raw: str | None, default: Any) -> Any:
    """Safely parse JSON column from CSV after cleaning literal `'null'`."""
    cleaned = clean_null_str(raw)
    if not cleaned:
        return default
    try:
        parsed = json.loads(cleaned)
        return default if parsed is None else parsed
    except Exception:
        return default


def extract_primary_phone(contacts_raw: str | None) -> tuple[list[dict[str, Any]], str]:
    """Parse `shops.contacts` JSON and extract the primary display phone number."""
    contacts = safe_json_loads(contacts_raw, [])
    if not isinstance(contacts, list):
        return [], ""
    primary = ""
    for entry in contacts:
        if isinstance(entry, dict):
            num = clean_null_str(str(entry.get("display_number") or entry.get("value") or ""))
            if num:
                primary = num
                break
    return contacts, primary


def parse_payment_options(payment_raw: str | None) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """Parse `shops.payment_options` JSON and extract verified in-person installment providers."""
    options = safe_json_loads(payment_raw, [])
    if not isinstance(options, list):
        return [], False, []
    providers: list[str] = []
    has_in_person = False
    for opt in options:
        if not isinstance(opt, dict):
            continue
        provider = clean_null_str(str(opt.get("provider_name") or ""))
        channel = str(opt.get("channel") or "").lower()
        if provider:
            if provider not in providers:
                providers.append(provider)
            if channel == "in_person":
                has_in_person = True
    # If providers exist even with channel='unknown', still surface them while flagging has_in_person
    return options, (has_in_person or len(providers) > 0), providers


def parse_product_specs(specs_raw: str | None) -> dict[str, str]:
    """Convert `products.specs` (`[{"key": ..., "value": ...}]` or `{...}`) into a flat `{key: value}` map."""
    parsed = safe_json_loads(specs_raw, [])
    result: dict[str, str] = {}
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                k = clean_null_str(str(item.get("key") or ""))
                v = clean_null_str(str(item.get("value") or ""))
                if k and v and k not in result:
                    result[k] = v
    elif isinstance(parsed, dict):
        for k, v in parsed.items():
            ks = clean_null_str(str(k))
            vs = clean_null_str(str(v))
            if ks and vs:
                result[ks] = vs
    return result


def canonicalize_spec_map(specs: dict[str, Any] | None) -> dict[str, str]:
    """Normalize ZWNJ/whitespace and merge synonymous display keys in product comparison tables."""
    if not specs:
        return {}
    out: dict[str, str] = {}
    for raw_k, raw_v in specs.items():
        val = clean_null_str(str(raw_v or ""))
        if not val:
            continue
        clean_k = _MULTI_SPACE_RE.sub(" ", str(raw_k or "").replace("\u200c", " ")).strip(" :،-")
        if not clean_k:
            continue
        norm_k = normalize_persian_text(clean_k)
        if norm_k in ("ظرفیت رم", "مقدار ram", "حافظه رم", "حافظه ram", "رم", "ram"):
            canon = "ظرفیت رم"
        elif norm_k in ("تراشه", "پردازنده", "پردازنده مرکزی", "مدل پردازنده", "چیپست", "cpu"):
            canon = "پردازنده / تراشه"
        elif norm_k in ("حافظه داخلی", "ظرفیت حافظه داخلی", "ظرفیت حافظه", "حافظه خشک", "ظرفیت ssd"):
            canon = "حافظه داخلی"
        elif norm_k in ("اندازه صفحه نمایش", "سایز صفحه نمایش", "صفحه نمایش"):
            canon = "صفحه نمایش"
        elif norm_k in ("brand", "برند"):
            canon = "برند"
        else:
            canon = clean_k
        if canon not in out:
            out[canon] = val
    return out


_NON_WARRANTY_MARKERS = (
    "بدون گارانتی",
    "فاقد گارانتی",
    "ندارد",
    "دست دوم",
    "استوک",
    "کارکرده",
    "ویترینی",
    "مشابه اصل",
    "های کپی",
    "طرح اصلی",
)

_TEST_ONLY_MARKERS = (
    "مهلت تست",
    "تحویل در حضور",
    "اصالت و سلامت",
    "اصالت کالا",
    "سلامت فیزیکی",
    "بازگشت کالا",
    "بازگشت وجه",
    "ضمانت تعویض",
    "ضمانت 7 روز",
    "ضمانت ۷ روز",
    "7 روز",
    "۷ روز",
)


def parse_warranty(warranty_raw: str | None) -> tuple[bool, str | None, int | None]:
    """Parse `offers.warranty` (JSON or plain Persian string) into `(has_official_warranty, provider, months)`."""
    cleaned = clean_null_str(warranty_raw)
    if not cleaned:
        return False, None, None

    desc: str | None = None
    prov: str | None = None
    months: int | None = None
    if cleaned.startswith("{"):
        data = safe_json_loads(cleaned, {})
        if isinstance(data, dict):
            desc = clean_null_str(str(data.get("description") or ""))
            prov = clean_null_str(str(data.get("provider") or ""))
            months_val = data.get("period_months")
            months = int(months_val) if isinstance(months_val, (int, float)) and int(months_val) > 0 else None
    else:
        desc = cleaned

    raw_label = desc or prov
    if not raw_label and not months:
        return False, None, None

    norm_check = normalize_persian_text(f"{desc or ''} {prov or ''}")
    if any(normalize_persian_text(m) in norm_check for m in _NON_WARRANTY_MARKERS):
        return False, None, 0

    has_duration_or_corp = bool(
        (months and months > 0)
        or any(tok in norm_check for tok in ("شرکتی", "ماهه", "ماه ", "ساله", "سال "))
    )
    if not has_duration_or_corp and any(normalize_persian_text(m) in norm_check for m in _TEST_ONLY_MARKERS):
        return False, None, 0

    if desc:
        label = desc
    elif prov and months:
        label = f"گارانتی {to_persian_digits(months)} ماهه {prov}"
    elif prov:
        label = f"گارانتی {prov}" if "گارانتی" not in prov else prov
    elif months:
        label = f"گارانتی {to_persian_digits(months)} ماهه"
    else:
        return False, None, None

    return True, label, months


_WEEKDAY_MAP = {
    0: "mon",
    1: "tue",
    2: "wed",
    3: "thu",
    4: "fri",
    5: "sat",
    6: "sun",
}


def evaluate_weekly_hours(
    weekly_hours: dict[str, Any] | str | None,
    now_dt: datetime | None = None,
) -> tuple[bool, str]:
    """Evaluate if a shop is currently open and return `(is_open_now, today_hours_fa)`."""
    if isinstance(weekly_hours, str):
        weekly_hours = safe_json_loads(weekly_hours, {})
    if not isinstance(weekly_hours, dict) or not weekly_hours:
        return True, "۱۰:۰۰ تا ۲۱:۰۰ (ساعت کاری معمول)"

    if now_dt is None:
        now_dt = datetime.now(_TEHRAN_TZ)
    elif now_dt.tzinfo is not None:
        now_dt = now_dt.astimezone(_TEHRAN_TZ)
    day_key = _WEEKDAY_MAP.get(now_dt.weekday(), "sat")
    day_info = weekly_hours.get(day_key)
    if not isinstance(day_info, dict):
        return True, "۱۰:۰۰ تا ۲۱:۰۰"

    status = str(day_info.get("status") or "").lower()
    shifts = day_info.get("shifts") or []
    if status == "closed" or not shifts:
        return False, "امروز تعطیل"

    shift_labels: list[str] = []
    is_open = False
    now_hhmm = now_dt.strftime("%H:%M:%S")
    for sh in shifts:
        if not isinstance(sh, dict):
            continue
        start = str(sh.get("start_time") or "09:00:00")
        end = str(sh.get("end_time") or "21:00:00")
        if start == "00:00:00" and end == "00:00:00":
            continue
        shift_labels.append(f"{to_persian_digits(start[:5])} تا {to_persian_digits(end[:5])}")
        if start <= now_hhmm <= end:
            is_open = True

    if not shift_labels:
        return False, "امروز تعطیل"
    return is_open, " / ".join(shift_labels)


def format_freshness_badge(last_price_changed_at: str | datetime | None) -> tuple[str, float]:
    """Return `(freshness_badge_fa, age_days)` from `offers.last_price_changed_at`."""
    if last_price_changed_at is None:
        return "بروزرسانی ثبت‌نشده", 14.0
    try:
        if isinstance(last_price_changed_at, str):
            cleaned = clean_null_str(last_price_changed_at)
            if not cleaned:
                return "بروزرسانی ثبت‌نشده", 14.0
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        else:
            dt = last_price_changed_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Dataset snapshot anchor is Oct 2026; measure relative to dataset max date or now
        anchor = datetime(2026, 10, 14, tzinfo=timezone.utc)
        delta_sec = max(60.0, abs((anchor - dt).total_seconds()))
        hours = delta_sec / 3600.0
        days = hours / 24.0
        if hours < 24:
            h_int = max(1, int(round(hours)))
            return f"بروزرسانی {to_persian_digits(h_int)} ساعت پیش", days
        d_int = max(1, int(round(days)))
        if d_int <= 30:
            return f"بروزرسانی {to_persian_digits(d_int)} روز پیش", days
        m_int = max(1, int(round(d_int / 30)))
        return f"بروزرسانی {to_persian_digits(m_int)} ماه پیش", days
    except Exception:
        return "بروزرسانی اخیر", 3.0
