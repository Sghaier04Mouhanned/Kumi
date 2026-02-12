import json
from pathlib import Path
from normalize import normalize_schedule
from indexer import build_indexes


def load_all_schedules(folder="processed"):
    all_items = []

    for file in Path(folder).glob("*.json"):
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)

        group = data["group_info"]["group_number"]
        normalized = normalize_schedule(data["schedule"], group)

        all_items.extend(normalized)

    return all_items


def main():
    schedule_items = load_all_schedules()
    indexes = build_indexes(schedule_items)

    final_data = {
        "all_classes": schedule_items,
        "indexes": indexes
    }

    with open("normalized_indexed_data.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2)

    print("✅ Normalization and indexing complete.")


if __name__ == "__main__":
    main()
