from __future__ import annotations

from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import (
    clean_text,
    detect_employment,
    detect_experience,
    find_salary_text,
    has_salary_hint,
    parse_published_dt,
    parse_salary_text,
    split_lines,
)


def scrape_hh_query(driver, query: str, *, hh_area: int | None = None, max_per_query: int | None = None) -> list[dict]:
    url = "https://hh.ru/search/vacancy"
    params = [
        f"text={quote_plus(query)}",
        "per_page=50",
        "search_field=name",
    ]
    if hh_area:
        params.append(f"area={hh_area}")
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
    if max_per_query:
        cards = cards[:max_per_query]
    results: list[dict] = []
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

            published_at = None
            for line in card_lines[:6]:
                published_at = parse_published_dt(line)
                if published_at:
                    break

            results.append(
                {
                    "id": f"hh:{vacancy_id}",
                    "title": title,
                    "salary": parse_salary_text(salary_text),
                    "url": vacancy_url,
                    "experience": detect_experience([experience, title] + card_lines),
                    "employment": detect_employment(card_lines),
                    "source_key": "hh",
                    "published_at": published_at.isoformat() if published_at else None,
                }
            )
        except Exception:
            continue
    return results

