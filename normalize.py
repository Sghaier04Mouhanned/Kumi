from collections import defaultdict

DAY_MAP = {
    "monday": "MON",
    "tuesday": "TUE",
    "wednesday": "WED",
    "thursday": "THU",
    "friday": "FRI"
}

# University timetables in this format list afternoon times without a leading
# "1" (e.g. "11:30 - 1:00 - 1:30 - 3:00 - 4:30" instead of 13:00/13:30/...).
# Classes never start this early in practice, so any hour below this is PM.
PM_ROLLOVER_HOUR = 8


def normalize_day(day: str) -> str:
    if not day:
        return "UNKNOWN"
    return DAY_MAP.get(day.lower().strip(), day.upper())


def _to_24h(hour: int) -> int:
    if hour != 12 and hour < PM_ROLLOVER_HOUR:
        return hour + 12
    return hour


def normalize_time(time_str: str):
    if not time_str:
        return "00:00", "00:00"

    time_str = time_str.replace("–", "-")
    start, end = time_str.split("-")

    def parse(part: str) -> str:
        hour_str, _, minute_str = part.strip().partition(":")
        hour = _to_24h(int(hour_str))
        minute = int(minute_str) if minute_str else 0
        return f"{hour:02d}:{minute:02d}"

    return parse(start), parse(end)


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


def merge_contiguous_sessions(items: list) -> list:
    """Collapse a course that spans several adjacent grid time-slots (e.g. a
    3-hour lecture split by the timetable's per-column layout into three
    1-hour rows) into a single session covering the full span.
    """
    def key(item):
        return (item.get("course_code"), item.get("group_number"), item.get("course_type"),
                item.get("instructor_name"), item.get("day"))

    grouped = defaultdict(list)
    for item in items:
        grouped[key(item)].append(item)

    merged = []
    for sessions in grouped.values():
        sessions.sort(key=lambda x: x["time_start"])
        current = None
        for item in sessions:
            if current is not None and current["time_end"] == item["time_start"]:
                current["time_end"] = item["time_end"]
                current["time"] = f"{current['time_start']} - {current['time_end']}"
            else:
                if current is not None:
                    merged.append(current)
                current = dict(item)
                current["time"] = f"{current['time_start']} - {current['time_end']}"
        if current is not None:
            merged.append(current)

    return merged
