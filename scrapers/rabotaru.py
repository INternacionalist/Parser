from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import (
    clean_text,
    detect_employment,
    detect_experience,
    detect_grade,
    parse_salary_text,
    split_lines,
)

DETAIL_DELAY_SECONDS = 1.0

CITY_RABOTA_SUBDOMAINS: dict[str, str] = {
    "Уфа": "ufa",
    "Москва": "www",
    "Санкт-Петербург": "spb",
    "Екатеринбург": "ekaterinburg",
    "Казань": "kazan",
    "Новосибирск": "novosibirsk",
    "Челябинск": "chelyabinsk",
    "Владивосток": "vladivostok",
}


def _base_url(city: str) -> str:
    sub = CITY_RABOTA_SUBDOMAINS.get(city)
    if not sub:
        sub = re.sub(r"\s+|-", "", city.lower())
    return f"https://{sub}.rabota.ru"


def _close_popups(driver) -> None:
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.2)
    except Exception:
        pass
    for selector in [
        "button[aria-label='Закрыть']",
        ".mobile-app-banner__close",
        ".ui-popup__close",
        ".r-btn_icon[aria-label='Закрыть']",
    ]:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, selector):
                try:
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(0.15)
                except Exception:
                    pass
        except Exception:
            pass


def _extract_vacancy(driver, url: str) -> dict:
    WebDriverWait(driver, 12).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "h1"))
    )
    _close_popups(driver)

    title = ""
    try:
        title = clean_text(
            driver.find_element(
                By.CSS_SELECTOR, "h1[itemprop='title'], h1.vacancy-card__title"
            ).text
        )
    except Exception:
        try:
            title = clean_text(driver.find_element(By.CSS_SELECTOR, "h1").text)
        except Exception:
            pass

    salary_text = ""
    try:
        salary_text = clean_text(
            driver.find_element(By.CSS_SELECTOR, "h3.vacancy-card__salary").text
        )
    except Exception:
        pass

    company = ""
    try:
        company = clean_text(
            driver.find_element(By.CSS_SELECTOR, "a[itemprop='legalName']").text
        )
    except Exception:
        pass

    experience_text = ""
    try:
        experience_text = clean_text(
            driver.find_element(By.CSS_SELECTOR, ".vacancy-requirements").text
        )
    except Exception:
        pass

    skills: list[str] = []
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, ".vacancy-card__skills-item"):
            txt = clean_text(el.text)
            if txt:
                skills.append(txt)
    except Exception:
        pass

    published_at = None
    try:
        meta_el = driver.find_element(By.CSS_SELECTOR, "meta[itemprop='datePosted']")
        published_at = clean_text(meta_el.get_attribute("content")) or None
    except Exception:
        pass

    employment_hint = ""
    try:
        emp_el = driver.find_element(By.CSS_SELECTOR, "meta[itemprop='employmentType']")
        employment_hint = clean_text(emp_el.get_attribute("content")) or ""
    except Exception:
        pass

    page_lines = split_lines(driver.find_element(By.TAG_NAME, "body").text)
    clean_url = url.split("?")[0].rstrip("/")

    return {
        "id": f"rabotaru:{clean_url}",
        "title": title,
        "company": company or None,
        "salary": parse_salary_text(salary_text),
        "url": clean_url,
        "experience": detect_experience([experience_text, title] + page_lines),
        "grade": detect_grade([title] + page_lines),
        "employment": detect_employment(
            ([employment_hint] if employment_hint else []) + page_lines
        ),
        "skills": skills or None,
        "source_key": "rabotaru",
        "published_at": published_at,
    }


def _hrefs_before_other_city(driver, base_url: str) -> list[str]:
    """Return vacancy hrefs from search results, stopping before другого города section."""
    return driver.execute_script(
        """
        const baseUrl = arguments[0];
        const pattern = /\\/vacancy\\/\\d+\\/?$/;

        let divider = null;
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            const t = node.textContent;
            if (t.includes('другого города') || t.includes('из другого')) {
                divider = node.parentElement;
                break;
            }
        }

        const seen = new Set();
        const results = [];

        for (const link of document.querySelectorAll('a[href*="/vacancy/"]')) {
            const href = (link.getAttribute('href') || '').split('?')[0].replace(/\\/$/, '');
            if (!pattern.test(href)) continue;

            const full = href.startsWith('http') ? href : baseUrl + href;
            if (seen.has(full)) continue;

            if (divider) {
                if (!(divider.compareDocumentPosition(link) & 2)) continue;
            }

            seen.add(full);
            results.push(full);
        }
        return results;
        """,
        base_url,
    )


def scrape_rabotaru_query(
    driver,
    query: str,
    *,
    city: str = "Уфа",
    max_per_query: int | None = None,
) -> list[dict]:
    base = _base_url(city)
    driver.get(f"{base}/vacancy/?query={quote_plus(query)}")
    _close_popups(driver)

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vacancy/']"))
        )
    except Exception:
        return []

    _close_popups(driver)
    hrefs = _hrefs_before_other_city(driver, base)
    if max_per_query:
        hrefs = hrefs[:max_per_query]

    results: list[dict] = []
    for href in hrefs:
        try:
            driver.get(href)
            results.append(_extract_vacancy(driver, href))
            time.sleep(DETAIL_DELAY_SECONDS)
        except Exception:
            continue

    return results
