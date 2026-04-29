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

CITY_ZARPLATA_SUBDOMAINS: dict[str, str] = {
    "Уфа": "ufa",
    "Москва": "www",
    "Санкт-Петербург": "spb",
    "Екатеринбург": "ekaterinburg",
    "Казань": "kazan",
    "Новосибирск": "novosibirsk",
    "Челябинск": "chelyabinsk",
    "Владивосток": "vladivostok",
}

CITY_ZARPLATA_AREAS: dict[str, int] = {
    "Уфа": 1359,
}


def _base_url(city: str) -> str:
    sub = CITY_ZARPLATA_SUBDOMAINS.get(city)
    if not sub:
        sub = re.sub(r"\s+|-", "", city.lower())
    return f"https://{sub}.zarplata.ru"


def _close_popups(driver) -> None:
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.3)
    except Exception:
        pass
    for selector in [
        "button[data-qa='close-popup']",
        "button[aria-label='Закрыть']",
        ".bloko-modal-close",
        "[data-qa='modal-close']",
        ".supernova-notification-close",
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
        EC.presence_of_element_located((By.CSS_SELECTOR, "h1[data-qa='vacancy-title']"))
    )
    _close_popups(driver)

    title = ""
    try:
        title = clean_text(
            driver.find_element(By.CSS_SELECTOR, "h1[data-qa='vacancy-title']").text
        )
    except Exception:
        try:
            title = clean_text(driver.find_element(By.CSS_SELECTOR, "h1").text)
        except Exception:
            pass

    salary_text = ""
    try:
        salary_text = clean_text(
            driver.find_element(By.CSS_SELECTOR, "[data-qa='vacancy-salary']").text
        )
    except Exception:
        pass

    company = ""
    try:
        company = clean_text(
            driver.find_element(By.CSS_SELECTOR, "[data-qa='vacancy-company-name']").text
        )
    except Exception:
        pass

    experience_text = ""
    try:
        experience_text = clean_text(
            driver.find_element(By.CSS_SELECTOR, "[data-qa='vacancy-experience']").text
        )
    except Exception:
        pass

    employment_text = ""
    try:
        employment_text = clean_text(
            driver.find_element(By.CSS_SELECTOR, "[data-qa='common-employment-text']").text
        )
    except Exception:
        pass

    published_at = None
    try:
        meta_el = driver.find_element(By.CSS_SELECTOR, "meta[itemprop='datePosted']")
        published_at = clean_text(meta_el.get_attribute("content")) or None
    except Exception:
        pass

    page_lines = split_lines(driver.find_element(By.TAG_NAME, "body").text)
    clean_url = url.split("?")[0].rstrip("/")

    return {
        "id": f"zarplataru:{clean_url}",
        "title": title,
        "company": company or None,
        "salary": parse_salary_text(salary_text),
        "url": clean_url,
        "experience": detect_experience([experience_text, title] + page_lines),
        "grade": detect_grade([title] + page_lines),
        "employment": detect_employment(
            ([employment_text] if employment_text else []) + page_lines
        ),
        "skills": None,
        "source_key": "zarplataru",
        "published_at": published_at,
    }


def _collect_hrefs(driver, base_url: str) -> list[str]:
    return driver.execute_script(
        """
        const baseUrl = arguments[0];
        const pattern = /\\/vacancy\\/\\d+\\/?$/;
        const seen = new Set();
        const results = [];
        for (const link of document.querySelectorAll('a[href*="/vacancy/"]')) {
            const href = (link.getAttribute('href') || '').split('?')[0].replace(/\\/$/, '');
            if (!pattern.test(href)) continue;
            const full = href.startsWith('http') ? href : baseUrl + href;
            if (seen.has(full)) continue;
            seen.add(full);
            results.push(full);
        }
        return results;
        """,
        base_url,
    )


def scrape_zarplataru_query(
    driver,
    query: str,
    *,
    city: str = "Уфа",
    max_per_query: int | None = None,
) -> list[dict]:
    base = _base_url(city)
    area = CITY_ZARPLATA_AREAS.get(city)
    url = f"{base}/search/vacancy?text={quote_plus(query)}"
    if area:
        url += f"&area={area}"
    driver.get(url)
    _close_popups(driver)

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vacancy/']"))
        )
    except Exception:
        return []

    _close_popups(driver)
    hrefs = _collect_hrefs(driver, base)
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
