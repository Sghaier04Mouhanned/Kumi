import re
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


# Matches "8", "8:30", "8AM", "8:30 PM", "12NOON", "12 MIDNIGHT" -- some
# timetables (confirmed: a real uploaded photo, non-TBS format) write times
# as a bare hour glued to AM/PM/NOON with no colon at all.
_TIME_PART_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM|NOON|MIDNIGHT)?$", re.IGNORECASE)


def _parse_time_part(part: str) -> str:
    part = part.strip()
    match = _TIME_PART_RE.match(part)
    if not match:
        raise ValueError(f"unrecognized time format: {part!r}")

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    marker = (match.group(3) or "").upper()

    if marker == "NOON":
        hour, minute = 12, 0
    elif marker == "MIDNIGHT":
        hour, minute = 0, 0
    elif marker == "PM":
        if hour != 12:
            hour += 12
    elif marker == "AM":
        if hour == 12:
            hour = 0
    else:
        # No explicit AM/PM marker -- this is TBS-style ("8:30 - 1:00")
        # where afternoon hours are written without a leading "1".
        hour = _to_24h(hour)

    return f"{hour:02d}:{minute:02d}"


def normalize_time(time_str: str):
    if not time_str:
        return "00:00", "00:00"

    time_str = time_str.replace("–", "-")
    start, end = time_str.split("-")
    return _parse_time_part(start), _parse_time_part(end)


def normalize_course(code: str) -> str:
    if not code:
        return "UNKNOWN"
    return code.replace(" ", "").upper()


# Confirmed on real data: some photos label a group as "G10 (22)" -- the
# "(22)" is the class's headcount, not part of the group's identity. Left
# in place, "G10 (22)" and "G10" from a different photo would be treated as
# two different groups instead of the same one.
_GROUP_SIZE_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")


def normalize_group(group: str) -> str:
    """Confirmed on real data: one photo's group label came through as a
    bare "5" while every other photo's came through as "G1"/"G2"/etc.,
    since that photo's on-screen label really was just the digit. Reading
    "BCOR111 - 5" next to "BCOR111 - G1" in the UI is confusing even
    though both are valid -- give every purely-numeric label the same "G"
    prefix so they read consistently."""
    if not group:
        return "UNKNOWN"
    group = _GROUP_SIZE_SUFFIX_RE.sub("", group.strip()).strip()
    if group.isdigit():
        return f"G{group}"
    return group.upper()


def normalize_course_type(course_type: str) -> str:
    """Confirmed on real data: the same session type comes back labeled
    differently across photos -- "L", "(L)", "Lecture" all mean the same
    thing, likewise "T"/"(T)"/"Tutorial". Collapse them to one canonical
    label so the review table doesn't show the same type three different
    ways depending on which photo a row came from."""
    if not course_type:
        return ""
    t = course_type.strip().lower().strip("()")
    if t == "l" or "lec" in t:
        return "Lecture"
    if t == "t" or "tut" in t:
        return "Tutorial"
    if "lab" in t:
        return "Lab"
    return course_type.strip()


def normalize_schedule(schedule: list, group_number: str):
    """Returns (normalized_items, skipped_rows). A row whose time can't be
    parsed is skipped rather than raising -- one unreadable row in a photo
    used to discard every other valid row on that same photo."""
    normalized_items = []
    skipped_rows = []

    for item in schedule:
        if not item.get("time"):
            continue

        try:
            start, end = normalize_time(item["time"])
        except (ValueError, AttributeError) as exc:
            skipped_rows.append((item, str(exc)))
            continue

        normalized_items.append({
            **item,
            "group_number": normalize_group(group_number),
            "day": normalize_day(item.get("day")),
            "course_code": normalize_course(item.get("course_code")),
            "course_type": normalize_course_type(item.get("course_type")),
            "time_start": start,
            "time_end": end
        })

    return normalized_items, skipped_rows


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
