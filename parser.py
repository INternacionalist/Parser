import json
import re
import signal
import time
from datetime import datetime
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


stop_requested = False


def signal_handler(signum, frame):
    del signum, frame
    global stop_requested
    stop_requested = True


signal.signal(signal.SIGINT, signal_handler)


DEFAULT_CITY = "Уфа"
CITY_ALIASES = {
    "уфа": "Уфа",
    "москва": "Москва",
    "владивосток": "Владивосток",
    "санкт-петербург": "Санкт-Петербург",
    "санкт петербург": "Санкт-Петербург",
    "питер": "Санкт-Петербург",
    "екатеринбург": "Екатеринбург",
    "казань": "Казань",
    "новосибирск": "Новосибирск",
}
CITY_HH_AREAS = {
    "Уфа": 99,
    "Москва": 1,
    "Санкт-Петербург": 2,
}
CITY_HABR_PATHS = {
    "Уфа": "ufa-175375",
}

CURRENT_CITY = DEFAULT_CITY
CURRENT_HH_AREA = CITY_HH_AREAS.get(DEFAULT_CITY)
CURRENT_HABR_PATH = CITY_HABR_PATHS.get(DEFAULT_CITY)

IT_QUERIES = [
    "Python разработчик",
    "Java разработчик",
    "Frontend разработчик",
    "Backend разработчик",
    "Fullstack разработчик",
    "DevOps инженер",
    "Data Scientist",
    "Тестировщик QA",
    "Android разработчик",
    "iOS разработчик",
    "1C разработчик",
    "Системный администратор",
]

GRADE_PATTERNS = [
    ("Стажер", [r"\bстаж[её]р\b", r"\bintern\b", r"\btrainee\b"]),
    ("Junior", [r"\bjunior\b", r"\bjr\b", r"\bджун\b", r"\bмладш"]),
    ("Middle", [r"\bmiddle\b", r"\bmid\b", r"\bмидд?л\b", r"\bсредн"]),
    ("Senior", [r"\bsenior\b", r"\bsr\b", r"\bсень[оё]р\b", r"\bстарш"]),
    ("Lead", [r"\blead\b", r"\bteam lead\b", r"\bтимлид\b", r"\bруковод"]),
]

ENABLED_SOURCES = [
    "hh",
    "habr",
    "remotejob",
]

SOURCE_LABELS = {
    "hh": "hh.ru",
    "habr": "career.habr.com",
    "remotejob": "remote-job.ru",
}


SOURCE_EMPTY_STREAK_LIMITS = {
    "hh": 4,
    "habr": 4,
    "remotejob": 4,
}
REQUEST_DELAY_BY_SOURCE = {
    "hh": 0.25,
    "habr": 0.2,
    "remotejob": 0.2,
}

def set_runtime_city(city: str | None) -> str:
    global CURRENT_CITY, CURRENT_HH_AREA, CURRENT_HABR_PATH
    CURRENT_CITY = normalize_city_name(city)
    CURRENT_HH_AREA = CITY_HH_AREAS.get(CURRENT_CITY)
    CURRENT_HABR_PATH = CITY_HABR_PATHS.get(CURRENT_CITY)
    return CURRENT_CITY


def normalize_city_name(city: str | None) -> str:
    value = re.sub(r"\s+", " ", (city or "")).strip()
    if not value:
        return DEFAULT_CITY
    lowered = value.lower()
    if lowered in CITY_ALIASES:
        return CITY_ALIASES[lowered]
    return " ".join(part.capitalize() for part in lowered.split(" "))


def make_driver(headless: bool = True) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "eager"
    options.add_argument("--incognito")
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(20)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


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
    values = []
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
    has_salary_words = bool(
        re.search(r"\b(зарплат|зп|оклад|доход|income|salary)\b", compact, re.IGNORECASE)
    )
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

    return {
        "from": sal_from,
        "to": sal_to,
        "currency": currency,
        "text": text if (sal_from or sal_to) else "Договорная",
    }


def detect_grade(texts: list[str]) -> str:
    combined = " ".join(clean_text(text) for text in texts).lower()
    for label, patterns in GRADE_PATTERNS:
        if any(re.search(pattern, combined, re.IGNORECASE) for pattern in patterns):
            return label
    return "Не указан"


def detect_employment(texts: list[str]) -> str:
    combined = " ".join(clean_text(text) for text in texts).lower()
    if any(re.search(pattern, combined, re.IGNORECASE) for pattern in [r"удал[её]н", r"remote", r"из дома", r"гибрид", r"hybrid"]):
        return "+ удаленка"
    return "Офис"


def find_salary_text(lines: list[str]) -> str:
    for line in lines:
        if has_salary_hint(line):
            return clean_text(line)
    return ""


def find_experience_text(lines: list[str]) -> str:
    experience_markers = [
        "опыт",
        "опыт работы",
        "требуемый опыт",
        "experience",
        "work experience",
    ]
    for line in lines:
        current = clean_text(line)
        lowered = normalize_separators(current).lower()
        if any(marker in lowered for marker in experience_markers):
            return current
    return ""


def extract_value_after_marker(lines: list[str], marker_variants: list[str], *, reject_empty_salary: bool = False) -> str:
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


def normalize_vacancy(item: dict) -> dict:
    salary = item.get("salary") or {"from": None, "to": None, "currency": None, "text": "Договорная"}
    title = clean_text(item.get("title"))
    url = clean_text(item.get("url"))
    source = item.get("source") or "unknown"
    vacancy_id = clean_text(item.get("id")) or f"{source}:{url or title}"

    experience = normalize_experience_text(item.get("experience"))
    if experience == "Нельзя определить" and source in {"habr", "remotejob"}:
        experience = "Нельзя определить"

    return {
        "id": vacancy_id,
        "title": title,
        "salary": salary,
        "url": url,
        "experience": experience,
        "grade": clean_text(item.get("grade")) or "Не указан",
        "employment": clean_text(item.get("employment")) or "Не указана",
        "source": SOURCE_LABELS.get(source, source),
        "source_key": source,
        "parsed_at": datetime.now().isoformat(),
    }


def scrape_hh_query(driver: webdriver.Chrome, query: str) -> list[dict]:
    search_text = query
    url = "https://hh.ru/search/vacancy"
    params = [
        f"text={quote_plus(search_text)}",
        "per_page=50",
        "search_field=name",
    ]
    if CURRENT_HH_AREA:
        params.append(f"area={CURRENT_HH_AREA}")
    driver.get(f"{url}?{'&'.join(params)}")

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "article.vacancy-search-item__card, div[data-qa='vacancy-serp__vacancy']")
            )
        )
    except Exception:
        return []

    cards = driver.find_elements(
        By.CSS_SELECTOR,
        "article.vacancy-search-item__card, div[data-qa='vacancy-serp__vacancy']",
    )
    results = []
    for card in cards:
        try:
            title_el = card.find_element(By.CSS_SELECTOR, "[data-qa='serp-item__title']")
            title = clean_text(title_el.text)
            raw_url = clean_text(title_el.get_attribute("href"))
            vacancy_url = raw_url.split("?")[0].rstrip("/")
            vacancy_id = vacancy_url.rsplit("/", 1)[-1]
            card_lines = split_lines(card.text)

            try:
                salary_text = clean_text(
                    card.find_element(By.CSS_SELECTOR, "[data-qa='vacancy-serp__vacancy-compensation']").text
                )
            except Exception:
                salary_text = ""
            if not has_salary_hint(salary_text):
                salary_text = find_salary_text(card_lines)

            try:
                experience = clean_text(
                    card.find_element(By.CSS_SELECTOR, "[data-qa='vacancy-serp__vacancy-work-experience']").text
                )
            except Exception:
                experience = ""
            experience = normalize_experience_text(experience)

            results.append(
                normalize_vacancy(
                    {
                        "id": f"hh:{vacancy_id}",
                        "title": title,
                        "salary": parse_salary_text(salary_text),
                        "url": vacancy_url,
                        "experience": detect_experience([experience, title] + card_lines),
                        "grade": detect_grade([title] + card_lines),
                        "employment": detect_employment(card_lines),
                        "source": "hh",
                    }
                )
            )
        except Exception:
            continue
    return results


def extract_card_text(driver: webdriver.Chrome, link) -> str:
    return driver.execute_script(
        """
        const link = arguments[0];
        let node = link;
        while (node && node !== document.body) {
          const text = (node.innerText || "").trim();
          if (text.split("\\n").length >= 4 && text.length > (link.innerText || "").length + 20) {
            return text;
          }
          node = node.parentElement;
        }
        return (link.parentElement && link.parentElement.innerText) || link.innerText || "";
        """,
        link,
    )


def parse_habr_card(title: str, url: str, block_text: str) -> dict | None:
    lines = split_lines(block_text)
    if not lines or not title or title not in block_text:
        return None
    salary_text = find_salary_text(lines)
    return normalize_vacancy(
        {
            "id": f"habr:{url}",
            "title": title,
            "salary": parse_salary_text(salary_text),
            "url": url,
            "experience": detect_experience([title] + lines),
            "grade": detect_grade([title] + lines),
            "employment": detect_employment(lines),
            "source": "habr",
        }
    )


def scrape_habr_query(driver: webdriver.Chrome, query: str) -> list[dict]:
    if CURRENT_HABR_PATH:
        url = f"https://career.habr.com/vacancies/{CURRENT_HABR_PATH}?q={quote_plus(query)}&type=all"
    else:
        url = f"https://career.habr.com/vacancies?q={quote_plus(f'{query} {CURRENT_CITY}')}&type=all"
    driver.get(url)

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vacancies/']"))
        )
    except Exception:
        return []

    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancies/']")
    results = []
    seen = set()
    for link in links:
        try:
            title = clean_text(link.text)
            href = clean_text(link.get_attribute("href"))
            if not title or not href:
                continue
            if "Откликнуться" in title or title == "Вакансии":
                continue
            if "/vacancies/skills/" in href or href in seen:
                continue
            block_text = extract_card_text(driver, link)
            item = parse_habr_card(title, href.split("?")[0], block_text)
            if not item:
                continue
            seen.add(href)
            results.append(item)
        except Exception:
            continue
    return results


def scrape_remotejob_query(driver: webdriver.Chrome, query: str) -> list[dict]:
    url = (
        "https://remote-job.ru/search"
        f"?search%5Bquery%5D={quote_plus(query)}"
        "&search%5BsearchType%5D=vacancy"
    )
    driver.get(url)

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vacancy/show/']"))
        )
    except Exception:
        return []

    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancy/show/']")
    results = []
    seen = set()
    for link in links:
        try:
            title = clean_text(link.text)
            href = clean_text(link.get_attribute("href"))
            if not title or not href or href in seen:
                continue

            block_text = extract_card_text(driver, link)
            lines = split_lines(block_text)
            salary_text = extract_value_after_marker(
                lines,
                ["Уровень зарплаты", "Зарплата", "Заработная плата"],
                reject_empty_salary=True,
            )
            if not has_salary_hint(salary_text):
                salary_text = find_salary_text(lines)

            results.append(
                normalize_vacancy(
                    {
                        "id": f"remotejob:{href}",
                        "title": title,
                        "salary": parse_salary_text(salary_text),
                        "url": href.split("?")[0],
                        "experience": detect_experience([title] + lines),
                        "grade": detect_grade([title] + lines),
                        "employment": detect_employment(lines + ["удаленная работа"]),
                        "source": "remotejob",
                    }
                )
            )
            seen.add(href)
        except Exception:
            continue
    return results


SCRAPERS = {
    "hh": scrape_hh_query,
    "habr": scrape_habr_query,
    "remotejob": scrape_remotejob_query,
}


def collect_all_vacancies(
    headless: bool = True,
    enabled_sources: list[str] | None = None,
    city: str | None = None,
) -> list[dict]:
    set_runtime_city(city)
    sources = enabled_sources or ENABLED_SOURCES
    print(f"Город: {CURRENT_CITY}")
    print(f"Источники: {', '.join(SOURCE_LABELS.get(src, src) for src in sources)}")
    driver = make_driver(headless=headless)
    all_vacancies: dict[str, dict] = {}
    try:
        for source_key in sources:
            scraper = SCRAPERS.get(source_key)
            if not scraper:
                continue
            print(f"\nИсточник: {SOURCE_LABELS.get(source_key, source_key)}")
            empty_streak = 0
            for query in IT_QUERIES:
                if stop_requested:
                    break
                print(f"  {query}...", end=" ", flush=True)
                items = scraper(driver, query)
                print(f"{len(items)}")
                if items:
                    empty_streak = 0
                else:
                    empty_streak += 1
                for item in items:
                    dedupe_key = item["url"] or item["id"] or item["title"]
                    if dedupe_key not in all_vacancies:
                        all_vacancies[dedupe_key] = item
                if empty_streak >= SOURCE_EMPTY_STREAK_LIMITS.get(source_key, 4):
                    print(f"  Пропускаю остаток запросов: подряд пусто {empty_streak} раз(а)")
                    break
                time.sleep(REQUEST_DELAY_BY_SOURCE.get(source_key, 0.2))
            if stop_requested:
                break
    finally:
        driver.quit()

    if stop_requested:
        return []

    vacancies = list(all_vacancies.values())
    print(f"\nСпарсено вакансий: {len(vacancies)}")
    return vacancies


def save_to_json(vacancies: list[dict], filepath: str = "vacancies.json", enabled_sources: list[str] | None = None) -> None:
    sources = enabled_sources or ENABLED_SOURCES
    out = {
        "meta": {
            "total": len(vacancies),
            "city": CURRENT_CITY,
            "sources": [SOURCE_LABELS.get(source, source) for source in sources],
            "parsed_at": datetime.now().isoformat(),
        },
        "vacancies": vacancies,
    }
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(out, file, ensure_ascii=False, indent=2)
