import json
import re
import signal
import time
from datetime import datetime, timedelta
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
    print("\nStop requested. Finishing current step...")
    stop_requested = True


signal.signal(signal.SIGINT, signal_handler)


CITY_NAME = "Уфа"
UFA_AREA_ID = 99
HABR_UFA_PATH = "ufa-175375"

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

MONTHS_RU = {
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

GRADE_PATTERNS = [
    ("Стажер", [r"\bстаж[её]р\b", r"\bintern\b", r"\btrainee\b"]),
    ("Junior", [r"\bjunior\b", r"\bjr\b", r"\bджун\b", r"\bмладш"]),
    ("Middle", [r"\bmiddle\b", r"\bmid\b", r"\bмидд?л\b", r"\bсредн"]),
    ("Senior", [r"\bsenior\b", r"\bsr\b", r"\bсень[оё]р\b", r"\bстарш"]),
    ("Lead", [r"\blead\b", r"\bteam lead\b", r"\bтимлид\b", r"\bруковод"]),
]

EMPLOYMENT_PATTERNS = [
    ("Гибрид", [r"гибрид", r"hybrid"]),
    ("Удаленка", [r"удал[её]н", r"remote", r"work from home", r"из дома"]),
    ("Полный день", [r"полный рабочий день", r"полная занятость", r"full[- ]time", r"full time"]),
]


def make_driver(headless: bool = True) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
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
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def split_lines(value: str | None) -> list[str]:
    return [
        clean_text(line)
        for line in (value or "").splitlines()
        if clean_text(line)
    ]


def normalize_separators(text: str) -> str:
    return (
        text.replace("\u202f", " ")
        .replace("\xa0", " ")
        .replace("–", "-")
        .replace("—", "-")
    )


def has_salary_hint(text: str) -> bool:
    compact = normalize_separators(clean_text(text))
    if not compact:
        return False
    has_digits = bool(re.search(r"\d", compact))
    has_currency = bool(re.search(r"(₽|руб|USD|EUR|\$|€|k\b)", compact, re.IGNORECASE))
    has_range = bool(re.search(r"\b(от|до)\b", compact, re.IGNORECASE))
    return has_digits and (has_currency or has_range)


def parse_salary_text(text: str) -> dict:
    text = clean_text(text)
    compact = normalize_separators(text)

    if not has_salary_hint(compact):
        return {"from": None, "to": None, "currency": None, "text": "Договорная"}

    nums = [
        int("".join(re.findall(r"\d+", part)))
        for part in re.findall(r"[\d\s]+", compact)
        if re.search(r"\d", part)
    ]

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


def parse_russian_date(text: str) -> str | None:
    value = clean_text(text).lower()
    if not value:
        return None

    now = datetime.now()
    hour_match = re.search(r"(\d+)\s*(час|часа|часов)\s*назад", value)
    minute_match = re.search(r"(\d+)\s*(минуту|минуты|минут|минута)\s*назад", value)
    day_ago_match = re.search(r"(\d+)\s*(день|дня|дней)\s*назад", value)
    week_ago_match = re.search(r"(\d+)\s*(неделю|недели|недель)\s*назад", value)

    if minute_match:
        return (now - timedelta(minutes=int(minute_match.group(1)))).isoformat()
    if hour_match:
        return (now - timedelta(hours=int(hour_match.group(1)))).isoformat()
    if day_ago_match:
        return (now - timedelta(days=int(day_ago_match.group(1)))).isoformat()
    if week_ago_match:
        return (now - timedelta(weeks=int(week_ago_match.group(1)))).isoformat()
    if "сегодня" in value:
        time_match = re.search(r"(\d{1,2}):(\d{2})", value)
        if time_match:
            return now.replace(
                hour=int(time_match.group(1)),
                minute=int(time_match.group(2)),
                second=0,
                microsecond=0,
            ).isoformat()
        return now.replace(second=0, microsecond=0).isoformat()
    if "вчера" in value:
        yesterday = now - timedelta(days=1)
        time_match = re.search(r"(\d{1,2}):(\d{2})", value)
        if time_match:
            return yesterday.replace(
                hour=int(time_match.group(1)),
                minute=int(time_match.group(2)),
                second=0,
                microsecond=0,
            ).isoformat()
        return yesterday.replace(second=0, microsecond=0).isoformat()

    match = re.search(r"(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?", value)
    if not match:
        return None

    day = int(match.group(1))
    month = MONTHS_RU.get(match.group(2))
    year = int(match.group(3)) if match.group(3) else now.year
    if not month:
        return None

    time_match = re.search(r"(\d{1,2}):(\d{2})", value)
    hour = int(time_match.group(1)) if time_match else 0
    minute = int(time_match.group(2)) if time_match else 0

    try:
        return datetime(year, month, day, hour, minute).isoformat()
    except ValueError:
        return None


def detect_experience(texts: list[str]) -> str:
    for text in texts:
        value = clean_text(text)
        lowered = value.lower()
        if re.search(r"без\s+опыта", value, re.IGNORECASE):
            return "Без опыта"
        if "опыт" not in lowered and "experience" not in lowered:
            continue

        match = re.search(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\b", normalize_separators(value))
        if match:
            left = int(match.group(1))
            right = int(match.group(2))
            if left <= 10 and right <= 10:
                return f"{left}-{right}"

        single_match = re.search(r"\bот\s+(\d{1,2})\s+до\s+(\d{1,2})\b", lowered)
        if single_match:
            left = int(single_match.group(1))
            right = int(single_match.group(2))
            if left <= 10 and right <= 10:
                return f"{left}-{right}"
    return "Без опыта"


def normalize_experience_text(text: str) -> str:
    value = clean_text(text)
    lowered = value.lower()

    if not value:
        return "Без опыта"
    if re.search(r"без\s+опыта", lowered):
        return "Без опыта"

    range_match = re.search(r"\b(?:от\s+)?(\d{1,2})\s*(?:-|–|до)\s*(\d{1,2})\b", normalize_separators(lowered))
    if range_match:
        left = int(range_match.group(1))
        right = int(range_match.group(2))
        if left <= 10 and right <= 10:
            return f"{left}-{right}"

    single_match = re.search(r"\b(\d{1,2})\b", lowered)
    if single_match:
        years = int(single_match.group(1))
        if years <= 10:
            return str(years)

    return "Без опыта"


def detect_grade(texts: list[str]) -> str:
    combined = " ".join(clean_text(text) for text in texts).lower()
    for label, patterns in GRADE_PATTERNS:
        if any(re.search(pattern, combined, re.IGNORECASE) for pattern in patterns):
            return label
    return "Не указан"


def detect_employment(texts: list[str]) -> str:
    combined = " ".join(clean_text(text) for text in texts).lower()
    if any(re.search(pattern, combined, re.IGNORECASE) for pattern in [r"удал[её]н", r"remote", r"из дома"]):
        return "+ удаленка"
    if any(re.search(pattern, combined, re.IGNORECASE) for pattern in [r"гибрид", r"hybrid"]):
        return "+ удаленка"
    return "Офис"


def find_salary_text(lines: list[str]) -> str:
    for line in lines:
        if has_salary_hint(line):
            return clean_text(line)
    return ""


def extract_value_after_marker(lines: list[str], marker_variants: list[str]) -> str:
    normalized_markers = [clean_text(marker).lower().rstrip(":") for marker in marker_variants]

    for index, line in enumerate(lines):
        current = clean_text(line)
        lowered = current.lower().rstrip(":")

        for marker in normalized_markers:
            if lowered == marker:
                if index + 1 < len(lines):
                    return clean_text(lines[index + 1])
            elif lowered.startswith(marker + ":"):
                return clean_text(current.split(":", 1)[1])
    return ""


def normalize_vacancy(item: dict) -> dict:
    salary = item.get("salary") or {"from": None, "to": None, "currency": None, "text": "Договорная"}
    published_text = clean_text(item.get("published_text") or item.get("published_at_text") or item.get("published_at"))
    published_at = item.get("published_at") or parse_russian_date(published_text) or datetime.now().isoformat()

    title = clean_text(item.get("title"))
    url = clean_text(item.get("url"))
    source = item.get("source") or "unknown"
    vacancy_id = clean_text(item.get("id")) or f"{source}:{url or title}"

    return {
        "id": vacancy_id,
        "title": title,
        "salary": salary,
        "url": url,
        "experience": clean_text(item.get("experience")) or "Без опыта",
        "grade": clean_text(item.get("grade")) or "Не указан",
        "employment": clean_text(item.get("employment")) or "Не указана",
        "source": SOURCE_LABELS.get(source, source),
        "source_key": source,
        "published_at": published_at,
        "published_text": published_text or "Не указана",
        "parsed_at": datetime.now().isoformat(),
    }


def scrape_hh_query(driver: webdriver.Chrome, query: str) -> list[dict]:
    url = (
        "https://hh.ru/search/vacancy"
        f"?text={quote_plus(query)}"
        f"&area={UFA_AREA_ID}"
        "&per_page=50"
        "&search_field=name"
    )
    driver.get(url)

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
            if not re.search(r"\d+\s*[-–]\s*\d+|без\s+опыта", experience, re.IGNORECASE):
                experience = detect_experience(card_lines)

            try:
                published_text = clean_text(
                    card.find_element(By.CSS_SELECTOR, "span[data-qa='vacancy-serp__vacancy-date']").text
                )
            except Exception:
                published_text = ""
            if not published_text:
                published_text = next((line for line in card_lines if parse_russian_date(line)), "")

            results.append(
                normalize_vacancy(
                    {
                        "id": f"hh:{vacancy_id}",
                        "title": title,
                        "salary": parse_salary_text(salary_text),
                        "url": vacancy_url,
                        "experience": experience,
                        "grade": detect_grade([title] + card_lines),
                        "employment": detect_employment(card_lines),
                        "source": "hh",
                        "published_text": published_text,
                    }
                )
            )
        except Exception:
            continue

    return results


def extract_habr_card_text(driver: webdriver.Chrome, link) -> str:
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
    if not lines or not title:
        return None

    if title not in block_text:
        return None

    salary_text = find_salary_text(lines)
    published_text = next((line for line in lines if parse_russian_date(line)), "")

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
            "published_text": published_text,
        }
    )


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

            block_text = extract_habr_card_text(driver, link)
            lines = split_lines(block_text)
            salary_text = extract_value_after_marker(
                lines,
                ["Уровень зарплаты", "Зарплата", "Заработная плата"],
            )
            if not has_salary_hint(salary_text):
                salary_text = find_salary_text(lines)

            experience_text = extract_value_after_marker(
                lines,
                ["Требуемый опыт работы", "Опыт работы", "Требования к опыту"],
            )
            experience_text = normalize_experience_text(experience_text)
            if experience_text == "Без опыта":
                experience_text = detect_experience(lines)

            published_text = next((line for line in lines if parse_russian_date(line)), "")

            results.append(
                normalize_vacancy(
                    {
                        "id": f"remotejob:{href}",
                        "title": title,
                        "salary": parse_salary_text(salary_text),
                        "url": href.split("?")[0],
                        "experience": experience_text,
                        "grade": detect_grade([title] + lines),
                        "employment": detect_employment(lines + ["удаленная работа"]),
                        "source": "remotejob",
                        "published_text": published_text,
                    }
                )
            )
            seen.add(href)
        except Exception:
            continue

    return results


def scrape_habr_query(driver: webdriver.Chrome, query: str) -> list[dict]:
    url = f"https://career.habr.com/vacancies/{HABR_UFA_PATH}?q={quote_plus(query)}&type=all"
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
            if "/vacancies/skills/" in href or f"/vacancies/{HABR_UFA_PATH}" in href:
                continue
            if href in seen:
                continue

            block_text = extract_habr_card_text(driver, link)
            item = parse_habr_card(title, href.split("?")[0], block_text)
            if not item:
                continue

            seen.add(href)
            results.append(item)
        except Exception:
            continue

    return results


SCRAPERS = {
    "hh": scrape_hh_query,
    "habr": scrape_habr_query,
    "remotejob": scrape_remotejob_query,
}


def collect_all_vacancies(headless: bool = False, enabled_sources: list[str] | None = None) -> list[dict]:
    sources = enabled_sources or ENABLED_SOURCES
    print(f"Parsing sources: {', '.join(SOURCE_LABELS.get(src, src) for src in sources)}")
    driver = make_driver(headless=headless)
    all_vacancies: dict[str, dict] = {}

    try:
        for source_key in sources:
            scraper = SCRAPERS.get(source_key)
            if not scraper:
                print(f"Skipping unknown source: {source_key}")
                continue

            print(f"\nSource: {SOURCE_LABELS.get(source_key, source_key)}")
            for query in IT_QUERIES:
                if stop_requested:
                    break

                print(f"  {query}")
                items = scraper(driver, query)
                new_count = 0

                for item in items:
                    dedupe_key = item["url"] or item["id"] or item["title"]
                    if dedupe_key not in all_vacancies:
                        all_vacancies[dedupe_key] = item
                        new_count += 1

                print(f"    found: {len(items)}, new: {new_count}")
                time.sleep(1.1)

            if stop_requested:
                break
    finally:
        driver.quit()

    if stop_requested:
        print("Parsing interrupted by user.")
        return []

    unique = list(all_vacancies.values())
    unique.sort(key=lambda item: item["published_at"], reverse=True)
    print(f"\nDone. Unique vacancies: {len(unique)}")
    return unique


def save_to_json(vacancies: list[dict], filepath: str = "vacancies.json", enabled_sources: list[str] | None = None) -> None:
    sources = enabled_sources or ENABLED_SOURCES
    out = {
        "meta": {
            "total": len(vacancies),
            "city": CITY_NAME,
            "sources": [SOURCE_LABELS.get(source, source) for source in sources],
            "parsed_at": datetime.now().isoformat(),
        },
        "vacancies": vacancies,
    }
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(out, file, ensure_ascii=False, indent=2)
    print(f"Saved to {filepath}: {len(vacancies)} vacancies")
