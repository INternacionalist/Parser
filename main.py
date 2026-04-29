import json
import os
import sys

from parser import ENABLED_SOURCES, SOURCE_LABELS, collect_all_vacancies, load_it_queries, normalize_city_name, save_to_json


OUTPUT_FILE = "vacancies.json"


def print_stats(vacancies: list[dict], city: str) -> None:
    total = len(vacancies)
    if not total:
        print("Нет вакансий.")
        return

    with_salary = sum(1 for item in vacancies if item["salary"]["from"] or item["salary"]["to"])
    by_source: dict[str, int] = {}
    by_experience: dict[str, int] = {}

    for item in vacancies:
        source = item.get("source", "Unknown")
        by_source[source] = by_source.get(source, 0) + 1

        experience = item.get("experience", "Не указан")
        by_experience[experience] = by_experience.get(experience, 0) + 1

    print("\n" + "=" * 50)
    print(f"СТАТИСТИКА: {city}")
    print("=" * 50)
    print(f"Всего вакансий:        {total}")
    print(f"С указанной зарплатой: {with_salary} ({with_salary / total * 100:.0f}%)")
    print(f"Источники:             {', '.join(SOURCE_LABELS.get(src, src) for src in ENABLED_SOURCES)}")

    print("\nПо источникам:")
    for source, count in sorted(by_source.items(), key=lambda pair: pair[1], reverse=True):
        print(f"  {count:>3}  {source}")

    print("\nПо опыту:")
    for experience, count in sorted(by_experience.items(), key=lambda pair: pair[1], reverse=True):
        print(f"  {count:>3}  {experience}")
    print("=" * 50)
    print("\nГотово. Открой index.html сам.")


def load_existing_count() -> tuple[int, str]:
    with open(OUTPUT_FILE, encoding="utf-8") as file:
        existing = json.load(file)
    count = existing.get("meta", {}).get("total", 0)
    parsed_at = existing.get("meta", {}).get("parsed_at", "")[:19]
    return count, parsed_at


def main() -> None:
    print("=" * 50)
    print("IT vacancies aggregator")
    print("=" * 50)

    queries = load_it_queries()
    print(f"Загружено запросов: {len(queries)} (из info_pars.txt)\n")

    city_input = input("Введите город: ").strip()
    city = normalize_city_name(city_input)
    print(f"Выбран город: {city}")

    limit_raw = input("Макс. вакансий на запрос (Enter = без лимита): ").strip()
    max_per_query = int(limit_raw) if limit_raw.isdigit() and int(limit_raw) > 0 else None
    print()

    if os.path.exists(OUTPUT_FILE):
        try:
            count, parsed_at = load_existing_count()
            answer = input(f"Найден {OUTPUT_FILE}: {count} вакансий ({parsed_at}). Перепарсить? [y/N]: ").strip().lower()
            if answer != "y":
                with open(OUTPUT_FILE, encoding="utf-8") as file:
                    existing = json.load(file)
                print_stats(existing.get("vacancies", []), existing.get("meta", {}).get("city", city))
                return
        except (json.JSONDecodeError, OSError, KeyError):
            print("Старый JSON поврежден, собираем заново.\n")

    vacancies = collect_all_vacancies(
        headless=True,
        enabled_sources=ENABLED_SOURCES,
        city=city,
        max_per_query=max_per_query,
        it_queries=queries,
    )
    if not vacancies:
        print("Не удалось собрать вакансии.")
        sys.exit(1)

    save_to_json(vacancies, OUTPUT_FILE, enabled_sources=ENABLED_SOURCES)
    print_stats(vacancies, city)


if __name__ == "__main__":
    main()
