from __future__ import annotations

import json
import re
import time
from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import (
    clean_text,
    detect_grade,
    detect_employment,
    detect_experience,
    find_salary_text,
    parse_published_dt,
    parse_salary_text,
    split_lines,
)

DETAIL_DELAY_SECONDS = 0.8


def _read_ssr_state(driver) -> dict | None:
    try:
        el = driver.find_element(By.CSS_SELECTOR, "script[data-ssr-state='true']")
        raw = clean_text(el.get_attribute("innerHTML"))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def _extract_habr_vacancy_details(driver, url: str) -> dict:
    wait = WebDriverWait(driver, 12)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .vacancy-show")))

    state = _read_ssr_state(driver)

    title = ""
    try:
        title = clean_text(driver.find_element(By.CSS_SELECTOR, "h1").text)
    except Exception:
        title = ""

    published_at = None
    try:
        dt = clean_text(driver.find_element(By.CSS_SELECTOR, "time[datetime]").get_attribute("datetime"))
        if dt:
            published_at = dt
    except Exception:
        published_at = None

    salary_text = ""
    try:
        salary_text = clean_text(driver.find_element(By.CSS_SELECTOR, ".vacancy-header__salary").text)
    except Exception:
        salary_text = ""

    company = ""
    try:
        company = clean_text(driver.find_element(By.CSS_SELECTOR, ".company_info .company_name a").text)
    except Exception:
        company = ""

    locations: list[str] = []
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, ".vacancy-meta .chip-with-icon__text"):
            txt = clean_text(el.text)
            if txt:
                locations.append(txt)
    except Exception:
        locations = []

    skills: list[str] = []
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, ".vacancy-meta .chip-without-icon__text"):
            txt = clean_text(el.text)
            if txt:
                skills.append(txt)
    except Exception:
        skills = []

    description = ""
    try:
        description = clean_text(driver.find_element(By.CSS_SELECTOR, ".vacancy-description__text").text)
    except Exception:
        description = ""

    if state and isinstance(state, dict):
        vacancy = (state.get("vacancy") or {}) if isinstance(state.get("vacancy"), dict) else {}
        company_state = (vacancy.get("company") or {}) if isinstance(vacancy.get("company"), dict) else {}
        if not company:
            company = clean_text(company_state.get("title"))
        if not published_at:
            published_at = clean_text(((vacancy.get("publishedDate") or {}) if isinstance(vacancy.get("publishedDate"), dict) else {}).get("date"))
        if not description:
            description = clean_text(vacancy.get("description"))

        if not skills:
            s = vacancy.get("skills")
            if isinstance(s, list):
                skills = [clean_text(x.get("title")) for x in s if isinstance(x, dict) and clean_text(x.get("title"))]
        if not locations:
            locs = vacancy.get("locations")
            if isinstance(locs, list):
                locations = [clean_text(x.get("title")) for x in locs if isinstance(x, dict) and clean_text(x.get("title"))]

        if not salary_text:
            sal = vacancy.get("salary")
            if isinstance(sal, dict):
                salary_text = clean_text(sal.get("formatted"))
        if salary_text and "зарплата не указана" in salary_text.lower():
            predicted = vacancy.get("predictedSalary")
            if isinstance(predicted, dict):
                formatted = clean_text(predicted.get("formatted"))
                if formatted:
                    salary_text = formatted

    published_dt = None
    if published_at and "T" not in published_at:
        published_dt = parse_published_dt(published_at)
        published_at = published_dt.isoformat() if published_dt else None

    page_lines = split_lines(driver.find_element(By.TAG_NAME, "body").text)

    return {
        "id": f"habr:{url}",
        "title": title,
        "company": company or None,
        "salary": parse_salary_text(salary_text),
        "url": url,
        "experience": detect_experience([title] + page_lines),
        "grade": detect_grade([title] + page_lines),
        "employment": detect_employment(page_lines),
        "locations": locations or None,
        "skills": skills or None,
        "description": description or None,
        "source_key": "habr",
        "published_at": published_at,
    }


def scrape_habr_query(driver, query: str, *, habr_path: str | None = None, city: str | None = None, max_per_query: int | None = None) -> list[dict]:
    if habr_path:
        url = f"https://career.habr.com/vacancies/{habr_path}?q={quote_plus(query)}&type=all"
    else:
        url = f"https://career.habr.com/vacancies?q={quote_plus(f'{query} {city or ''}')}&type=all"
    driver.get(url)

    try:
        WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vacancies/']")))
    except Exception:
        return []

    hrefs: list[str] = []
    seen: set[str] = set()
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancies/']"):
        href = clean_text(a.get_attribute("href"))
        if not href:
            continue
        href = href.split("?", 1)[0].rstrip("/")
        if not re.search(r"/vacancies/\d+$", href):
            continue
        if href in seen:
            continue
        seen.add(href)
        hrefs.append(href)

    if max_per_query:
        hrefs = hrefs[:max_per_query]
    results: list[dict] = []
    for href in hrefs:
        try:
            driver.get(href)
            item = _extract_habr_vacancy_details(driver, href)
            results.append(item)
            time.sleep(DETAIL_DELAY_SECONDS)
        except Exception:
            continue
    return results

