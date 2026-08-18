from collections import defaultdict


def build_indexes(schedule_items: list):
    by_course = defaultdict(list)
    by_instructor = defaultdict(list)
    by_group = defaultdict(list)

    for item in schedule_items:
        by_course[item["course_code"]].append(item)
        by_instructor[item["instructor_name"]].append(item)
        by_group[item["group_number"]].append(item)

    return {
        "by_course": dict(by_course),
        "by_instructor": dict(by_instructor),
        "by_group": dict(by_group)
    }
