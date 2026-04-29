from __future__ import annotations

import time
from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import (
    clean_text,
    detect_employment,
    detect_experience,
    extract_value_after_marker,
    find_salary_text,
    has_salary_hint,
    parse_published_dt,
    parse_salary_text,
    split_lines,
)


DETAIL_DELAY_SECONDS = 1.2


def scrape_remotejob_query(driver, query: str, *, max_per_query: int | None = None) -> list[dict]:
    url = (
        "https://remote-job.ru/search"
        f"?search%5Bquery%5D={quote_plus(query)}"
        "&search%5BsearchType%5D=vacancy"
    )
    driver.get(url)

    try:
        WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vacancy/show/']")))
    except Exception:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    hrefs: list[str] = []
    for link in driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancy/show/']"):
        href = clean_text(link.get_attribute("href"))
        if not href:
            continue
        href = href.split("#", 1)[0]
        if href in seen:
            continue
        seen.add(href)
        hrefs.append(href)

    if max_per_query:
        hrefs = hrefs[:max_per_query]
    wait = WebDriverWait(driver, 12)
    for href in hrefs:
        try:
            driver.get(href)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))

            title = ""
            try:
                title = clean_text(driver.find_element(By.CSS_SELECTOR, "h1").text)
            except Exception:
                title = ""

            company = ""
            try:
                company = clean_text(driver.find_element(By.CSS_SELECTOR, "h4 a").text)
            except Exception:
                company = ""

            published_at = None
            try:
                date_text = clean_text(driver.find_element(By.CSS_SELECTOR, ".row.valign-flex-end small").text)
                published_at = parse_published_dt(date_text)
            except Exception:
                published_at = None

            salary_text = ""
            experience_text = ""
            try:
                salary_text = clean_text(
                    driver.find_element(
                        By.XPATH,
                        "//*[contains(normalize-space(), 'Уровень зарплаты')]/following::*[1]",
                    ).text
                )
            except Exception:
                try:
                    salary_text = clean_text(driver.find_element(By.CSS_SELECTOR, ".panel-heading b").text)
                except Exception:
                    salary_text = ""

            try:
                experience_text = clean_text(
                    driver.find_element(
                        By.XPATH,
                        "//*[contains(normalize-space(), 'Требуемый опыт')]/following::*[1]",
                    ).text
                )
            except Exception:
                experience_text = ""

            page_lines = split_lines(driver.find_element(By.TAG_NAME, "body").text)

            if not has_salary_hint(salary_text):
                salary_text = extract_value_after_marker(
                    page_lines,
                    ["Уровень зарплаты", "Зарплата", "Заработная плата"],
                    reject_empty_salary=True,
                )
            if not has_salary_hint(salary_text):
                salary_text = find_salary_text(page_lines)

            results.append(
                {
                    "id": f"remotejob:{href}",
                    "title": title or clean_text(href),
                    "company": company or None,
                    "salary": parse_salary_text(salary_text),
                    "url": href.split("?")[0],
                    "experience": detect_experience([experience_text, title] + page_lines),
                    "employment": detect_employment(page_lines + ["удаленная работа"]),
                    "source_key": "remotejob",
                    "published_at": published_at.isoformat() if published_at else None,
                }
            )

            time.sleep(DETAIL_DELAY_SECONDS)
        except Exception:
            continue
    return results

