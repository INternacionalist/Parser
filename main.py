import json
import os
import sys

from parser import ENABLED_SOURCES, SOURCE_LABELS, collect_all_vacancies, save_to_json


OUTPUT_FILE = "vacancies.json"


def print_stats(vacancies: list[dict]) -> None:
    total = len(vacancies)
    if not total:
        print("No vacancies found.")
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
    print("STATS")
    print("=" * 50)
    print(f"Total vacancies:   {total}")
    print(f"With salary:       {with_salary} ({with_salary / total * 100:.0f}%)")
    print(f"Sources enabled:   {', '.join(SOURCE_LABELS.get(src, src) for src in ENABLED_SOURCES)}")
    print("\nBy source:")
    for source, count in sorted(by_source.items(), key=lambda pair: pair[1], reverse=True):
        print(f"  {count:>3}  {source}")

    print("\nBy experience:")
    for experience, count in sorted(by_experience.items(), key=lambda pair: pair[1], reverse=True):
        print(f"  {count:>3}  {experience}")
    print("=" * 50)
    print("\nOpen index.html in a browser after parsing.")


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
    print(f"Sources: {', '.join(SOURCE_LABELS.get(src, src) for src in ENABLED_SOURCES)}\n")

    if os.path.exists(OUTPUT_FILE):
        try:
            count, parsed_at = load_existing_count()
            print(f"Found {OUTPUT_FILE}: {count} vacancies ({parsed_at})")
            answer = input("Re-parse now? [y/N]: ").strip().lower()
            if answer != "y":
                with open(OUTPUT_FILE, encoding="utf-8") as file:
                    existing = json.load(file)
                print_stats(existing.get("vacancies", []))
                return
        except (json.JSONDecodeError, OSError, KeyError):
            print("Existing JSON is broken. Rebuilding.\n")

    vacancies = collect_all_vacancies(headless=True, enabled_sources=ENABLED_SOURCES)
    if not vacancies:
        print("Could not collect vacancies.")
        sys.exit(1)

    save_to_json(vacancies, OUTPUT_FILE, enabled_sources=ENABLED_SOURCES)
    print_stats(vacancies)


if __name__ == "__main__":
    main()
