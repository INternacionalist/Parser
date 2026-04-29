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
    detect_employment,
    detect_experience,
    detect_grade,
    parse_salary_text,
    split_lines,
)

DETAIL_DELAY_SECONDS = 1.0

CITY_SJ_SUBDOMAINS: dict[str, str] = {
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
    sub = CITY_SJ_SUBDOMAINS.get(city)
    if not sub:
        sub = re.sub(r"\s+|-", "", city.lower())
    return f"https://{sub}.superjob.ru"


def _read_jsonld(driver) -> dict:
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "script[type='application/ld+json']"):
            try:
                data = json.loads(el.get_attribute("innerHTML") or "")
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    return data
            except Exception:
                continue
    except Exception:
        pass
    return {}


def _extract_vacancy(driver, url: str) -> dict:
    WebDriverWait(driver, 12).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "h1"))
    )

    jld = _read_jsonld(driver)

    title = clean_text(jld.get("title", ""))
    if not title:
        try:
            title = clean_text(driver.find_element(By.CSS_SELECTOR, "h1").text)
        except Exception:
            pass

    company = ""
    org = jld.get("hiringOrganization", {})
    if isinstance(org, dict):
        company = clean_text(org.get("name", ""))
    if not company:
        try:
            company = clean_text(
                driver.find_element(By.CSS_SELECTOR, "a[href*='/clients/']").text
            )
        except Exception:
            pass

    published_at = clean_text(jld.get("datePosted", "")) or None

    salary_text = ""
    try:
        raw = clean_text(driver.find_element(By.CSS_SELECTOR, "span.GfOgl").text)
        if raw and "договор" not in raw.lower():
            salary_text = raw
    except Exception:
        pass

    experience_text = ""
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "span.KqrLZ"):
            txt = clean_text(el.text)
            if "опыт" in txt.lower():
                experience_text = txt
                break
    except Exception:
        pass

    skills: list[str] = []
    try:
        for el in driver.find_elements(
            By.CSS_SELECTOR, "ul._8jaXR li div[class*='f-test-tag-'] span"
        ):
            txt = clean_text(el.text)
            if txt:
                skills.append(txt)
    except Exception:
        pass

    page_lines = split_lines(driver.find_element(By.TAG_NAME, "body").text)
    clean_url = url.split("?")[0].rstrip("/")

    return {
        "id": f"superjob:{clean_url}",
        "title": title,
        "company": company or None,
        "salary": parse_salary_text(salary_text),
        "url": clean_url,
        "experience": detect_experience([experience_text, title] + page_lines),
        "grade": detect_grade([title] + page_lines),
        "employment": detect_employment(page_lines),
        "skills": skills or None,
        "source_key": "superjob",
        "published_at": published_at,
    }


def _hrefs_before_other_city(driver, base_url: str) -> list[str]:
    return driver.execute_script(
        """
        const baseUrl = arguments[0];
        const pattern = /\\/vakansii\\/[\\w-]+-\\d+\\.html$/;

        let divider = null;
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            if (node.textContent.includes('другого города')) {
                divider = node.parentElement;
                break;
            }
        }

        const seen = new Set();
        const results = [];

        for (const link of document.querySelectorAll('a[href*="/vakansii/"]')) {
            const href = (link.getAttribute('href') || '').split('?')[0];
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


def scrape_superjob_query(
    driver,
    query: str,
    *,
    city: str = "Уфа",
    max_per_query: int | None = None,
) -> list[dict]:
    base = _base_url(city)
    driver.get(f"{base}/vacancy/search/?keywords={quote_plus(query)}")

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vakansii/']"))
        )
    except Exception:
        return []

    hrefs = _hrefs_before_other_city(driver, base)
    if max_per_query:
        hrefs = hrefs[:max_per_query]

    results: list[dict] = []
    main_window = driver.current_window_handle

    for href in hrefs:
        try:
            driver.execute_script("window.open(arguments[0], '_blank');", href)
            new_win = [w for w in driver.window_handles if w != main_window][-1]
            driver.switch_to.window(new_win)
            try:
                results.append(_extract_vacancy(driver, href))
            finally:
                driver.close()
                driver.switch_to.window(main_window)
            time.sleep(DETAIL_DELAY_SECONDS)
        except Exception:
            try:
                driver.switch_to.window(main_window)
            except Exception:
                pass
            continue

    return results
