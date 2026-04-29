import re
from datetime import datetime, timedelta


GRADE_PATTERNS = [
    ("Стажер", [r"\bстаж[её]р\b", r"\bintern\b", r"\btrainee\b"]),
    ("Junior", [r"\bjunior\b", r"\bjr\b", r"\bджун\b", r"\bмладш"]),
    ("Middle", [r"\bmiddle\b", r"\bmid\b", r"\bмидд?л\b", r"\bсредн"]),
    ("Senior", [r"\bsenior\b", r"\bsr\b", r"\bсень[оё]р\b", r"\bстарш"]),
    ("Lead", [r"\blead\b", r"\bteam lead\b", r"\bтимлид\b", r"\bруковод"]),
]


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def split_lines(value: str | None) -> list[str]:
    return [clean_text(line) for line in (value or "").splitlines() if clean_text(line)]


def normalize_separators(text: str) -> str:
    return (
        text.replace("\u202f", " ")
        .replace("\xa0", " ")
        .replace("–", "-")
        .replace("—", "-")
    )


def has_month_or_date_context(text: str) -> bool:
    lowered = normalize_separators(clean_text(text)).lower()
    if not lowered:
        return False
    month_pattern = (
        r"\b(?:январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|"
        r"июл[ья]|август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])\b"
    )
    return bool(
        re.search(month_pattern, lowered)
        or re.search(r"\b20\d{2}\b", lowered)
        or re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", lowered)
        or re.search(r"\b\d{1,2}\s+[а-яё]+\s+20\d{2}\b", lowered)
    )


def extract_salary_numbers(text: str) -> list[int]:
    compact = normalize_separators(clean_text(text))
    values: list[int] = []
    for match in re.finditer(r"\d[\d\s]{0,10}\d|\d", compact):
        digits = "".join(re.findall(r"\d+", match.group(0)))
        if digits:
            values.append(int(digits))
    return values


def looks_like_salary_amount(value: int, text: str) -> bool:
    lowered = normalize_separators(clean_text(text)).lower()
    has_foreign_currency = bool(re.search(r"(usd|eur|\$|€)", lowered, re.IGNORECASE))
    has_k_suffix = bool(re.search(r"\b\d+(?:[.,]\d+)?\s*k\b", lowered, re.IGNORECASE))
    if has_foreign_currency or has_k_suffix:
        return 1 <= value <= 1_000_000
    return 10_000 <= value <= 10_000_000


def has_salary_hint(text: str) -> bool:
    compact = normalize_separators(clean_text(text))
    if not compact:
        return False
    if has_month_or_date_context(compact):
        return False
    numbers = extract_salary_numbers(compact)
    has_valid_amount = any(looks_like_salary_amount(value, compact) for value in numbers)
    has_currency = bool(re.search(r"(₽|руб|USD|EUR|\$|€|k\b)", compact, re.IGNORECASE))
    has_salary_words = bool(re.search(r"\b(зарплат|зп|оклад|доход|income|salary)\b", compact, re.IGNORECASE))
    return has_valid_amount and (has_currency or has_salary_words)


def is_empty_salary_text(text: str) -> bool:
    value = clean_text(text).lower()
    if not value:
        return True
    return any(
        marker in value
        for marker in [
            "з.п. не указана",
            "зп не указана",
            "зарплата не указана",
            "уровень зарплаты",
            "не указана",
            "не указан",
        ]
    )


def parse_salary_text(text: str) -> dict:
    text = clean_text(text)
    compact = normalize_separators(text)
    if len(compact) > 30:
        return {"from": None, "to": None, "currency": None, "text": "Договорная"}
    if is_empty_salary_text(compact):
        return {"from": None, "to": None, "currency": None, "text": "Договорная"}
    if not has_salary_hint(compact):
        return {"from": None, "to": None, "currency": None, "text": "Договорная"}

    nums = [value for value in extract_salary_numbers(compact) if looks_like_salary_amount(value, compact)]
    sal_from = None
    sal_to = None
    lowered = compact.lower()
    if "от" in lowered and "до" in lowered and len(nums) >= 2:
        sal_from, sal_to = nums[0], nums[1]
    elif "от" in lowered and nums:
        sal_from = nums[0]
    elif "до" in lowered and nums:
        sal_to = nums[0]
    elif len(nums) >= 2:
        sal_from, sal_to = nums[0], nums[1]
    elif nums:
        sal_from = nums[0]

    currency = None
    if re.search(r"(₽|руб)", compact, re.IGNORECASE):
        currency = "RUR"
    elif "$" in compact:
        currency = "USD"
    elif "€" in compact:
        currency = "EUR"

    return {"from": sal_from, "to": sal_to, "currency": currency, "text": text if (sal_from or sal_to) else "Договорная"}


def detect_employment(texts: list[str]) -> str:
    combined = " ".join(clean_text(text) for text in texts).lower()
    if any(re.search(pattern, combined, re.IGNORECASE) for pattern in [r"удал[её]н", r"remote", r"из дома", r"гибрид", r"hybrid"]):
        return "+ удаленка"
    return "Офис"


def detect_grade(texts: list[str]) -> str:
    combined = " ".join(clean_text(text) for text in texts).lower()
    for label, patterns in GRADE_PATTERNS:
        if any(re.search(pattern, combined, re.IGNORECASE) for pattern in patterns):
            return label
    return "Не указан"


def find_salary_text(lines: list[str]) -> str:
    for line in lines:
        if has_salary_hint(line):
            return clean_text(line)
    return ""


def find_experience_text(lines: list[str]) -> str:
    experience_markers = ["опыт", "опыт работы", "требуемый опыт", "experience", "work experience"]
    for line in lines:
        current = clean_text(line)
        lowered = normalize_separators(current).lower()
        if any(marker in lowered for marker in experience_markers):
            return current
    return ""


def normalize_experience_text(text: str) -> str:
    value = clean_text(text)
    lowered = normalize_separators(value).lower()
    if not value:
        return "Нельзя определить"
    if re.search(r"без\s+опыта|no experience|опыт не требуется", lowered):
        return "Без опыта"

    range_match = re.search(
        r"\b(?:от\s+)?(\d{1,2})\s*(?:-|до|–|—)\s*(\d{1,2})\s*(?:лет|года|год)?\b",
        lowered,
    )
    if range_match:
        left = int(range_match.group(1))
        right = int(range_match.group(2))
        if left <= 15 and right <= 15 and left <= right:
            return f"{left}-{right}"

    plus_match = re.search(
        r"\b(?:от\s+)?(\d{1,2})\s*\+\s*(?:лет|года|год)?\b|\b(?:от|более|свыше|more than)\s+(\d{1,2})\s*(?:лет|года|год)?\b",
        lowered,
    )
    if plus_match:
        years = int(plus_match.group(1) or plus_match.group(2))
        if years <= 15:
            return f"{years}+"

    single_match = re.search(r"\b(\d{1,2})\s*(?:лет|года|год)\b", lowered)
    if single_match:
        years = int(single_match.group(1))
        if years <= 15:
            return str(years)

    compact_match = re.search(r"\b(\d{1,2})-(\d{1,2})\b", lowered)
    if compact_match:
        left = int(compact_match.group(1))
        right = int(compact_match.group(2))
        if left <= 15 and right <= 15 and left <= right:
            return f"{left}-{right}"

    return "Нельзя определить"


def detect_experience(texts: list[str]) -> str:
    combined = [clean_text(text) for text in texts if clean_text(text)]
    for text in combined:
        normalized = normalize_experience_text(text)
        if normalized != "Нельзя определить":
            return normalized
    marker_text = find_experience_text(combined)
    if marker_text:
        normalized = normalize_experience_text(marker_text)
        if normalized != "Нельзя определить":
            return normalized
    return "Нельзя определить"


def extract_value_after_marker(
    lines: list[str],
    marker_variants: list[str],
    *,
    reject_empty_salary: bool = False,
) -> str:
    normalized_markers = [clean_text(marker).lower().rstrip(":") for marker in marker_variants]
    for index, line in enumerate(lines):
        current = clean_text(line)
        lowered = current.lower().rstrip(":")
        for marker in normalized_markers:
            if lowered == marker and index + 1 < len(lines):
                candidate = clean_text(lines[index + 1])
                if reject_empty_salary and is_empty_salary_text(candidate):
                    return ""
                return candidate
            if lowered.startswith(marker + ":"):
                candidate = clean_text(current.split(":", 1)[1])
                if reject_empty_salary and is_empty_salary_text(candidate):
                    return ""
                return candidate
    return ""


_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def parse_published_dt(text: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    lowered = normalize_separators(clean_text(text)).lower()
    if not lowered:
        return None
    if "сегодня" in lowered:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "вчера" in lowered:
        d = now - timedelta(days=1)
        return d.replace(hour=0, minute=0, second=0, microsecond=0)

    m = re.search(r"\b(\d{1,2})\s+([а-яё]+)(?:\s+(20\d{2}))?\b", lowered)
    if m:
        day = int(m.group(1))
        month_name = m.group(2)
        year_text = m.group(3)
        month = _RU_MONTHS.get(month_name)
        if month:
            year = int(year_text) if year_text else now.year
            try:
                dt = datetime(year, month, day)
            except ValueError:
                return None
            if not year_text and dt > now + timedelta(days=1):
                try:
                    dt = datetime(year - 1, month, day)
                except ValueError:
                    return None
            return dt

    m2 = re.search(r"\b(\d{1,3})\s+(минут|час|часа|часов|день|дня|дней|недел|месяц|месяца|месяцев)\s+назад\b", lowered)
    if m2:
        n = int(m2.group(1))
        unit = m2.group(2)
        if unit.startswith("минут"):
            return now - timedelta(minutes=n)
        if unit.startswith("час"):
            return now - timedelta(hours=n)
        if unit.startswith("д"):
            return now - timedelta(days=n)
        if unit.startswith("недел"):
            return now - timedelta(days=7 * n)
        if unit.startswith("месяц"):
            return now - timedelta(days=30 * n)
    if "неделю назад" in lowered:
        return now - timedelta(days=7)
    if "месяц назад" in lowered:
        return now - timedelta(days=30)
    return None


def humanize_age(published_at: datetime | None, now: datetime | None = None) -> str | None:
    if not published_at:
        return None
    now = now or datetime.now()
    delta = now - published_at
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    minutes = seconds // 60
    hours = seconds // 3600
    days = seconds // 86400
    if minutes < 60:
        return f"{minutes} мин назад"
    if hours < 24:
        return f"{hours} ч назад"
    if days < 7:
        return f"{days} дн назад"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} нед назад"
    months = days // 30
    return f"{months} мес назад"

