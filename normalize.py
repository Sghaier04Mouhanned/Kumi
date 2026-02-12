DAY_MAP = {
    "monday": "MON",
    "tuesday": "TUE",
    "wednesday": "WED",
    "thursday": "THU",
    "friday": "FRI"
}


def normalize_day(day: str) -> str:
    if not day:
        return "UNKNOWN"
    return DAY_MAP.get(day.lower().strip(), day.upper())


def normalize_time(time_str: str):
    if not time_str:
        return "00:00", "00:00"
    
    time_str = time_str.replace("–", "-")
    start, end = time_str.split("-")
    
    return start.strip().zfill(5), end.strip().zfill(5)


def normalize_course(code: str) -> str:
    if not code:
        return "UNKNOWN"
    return code.replace(" ", "").upper()


def normalize_schedule(schedule: list, group_number: str):
    normalized_items = []

    for item in schedule:
        if not item.get("time"):
            continue

        start, end = normalize_time(item["time"])

        normalized_items.append({
            **item,
            "group_number": group_number,
            "day": normalize_day(item.get("day")),
            "course_code": normalize_course(item.get("course_code")),
            "time_start": start,
            "time_end": end
        })

    return normalized_items
