"""Deterministic timetable generation: backtracking search over hard
constraints, weighted scoring over soft preferences. No external solver
library and no LLM in this path -- see the design notes in the PR/README
for why (reliability + zero marginal cost per generation).
"""

from collections import defaultdict

from backend.models import (
    ClassSession,
    CourseConflict,
    GenerateRequest,
    GenerateResponse,
    Preferences,
    TimetableResult,
)

DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

EARLY_THRESHOLD_MIN = 9 * 60  # 09:00
LATE_THRESHOLD_MIN = 16 * 60  # 16:00
NODE_CAP = 50_000

WEIGHTS = {
    "preferred_instructor": 8.0,
    "preferred_group": 8.0,
    "preferred_day": 3.0,
    "avoid_early_per_min": 0.5,
    "avoid_late_per_min": 0.5,
    "free_day_bonus": 20.0,
    "gap_penalty_per_min": 0.15,
    "compactness_penalty_per_day": 4.0,
}


def _time_to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _day_sort_key(day: str) -> int:
    return DAY_ORDER.index(day) if day in DAY_ORDER else len(DAY_ORDER)


def _ranges_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    return _time_to_minutes(start_a) < _time_to_minutes(end_b) and _time_to_minutes(start_b) < _time_to_minutes(end_a)


def _sessions_overlap(a: ClassSession, b: ClassSession) -> bool:
    return a.day == b.day and _ranges_overlap(a.time_start, a.time_end, b.time_start, b.time_end)


def _group_conflicts(group_a: list[ClassSession], group_b: list[ClassSession]) -> bool:
    return any(_sessions_overlap(s1, s2) for s1 in group_a for s2 in group_b)


def _backtrack_search(
    course_order: list[str],
    options_by_course: dict[str, dict[str, list[ClassSession]]],
) -> list[list[ClassSession]]:
    results: list[list[ClassSession]] = []
    node_count = 0

    def backtrack(index: int, assigned: list[ClassSession], chosen: list[ClassSession]) -> None:
        nonlocal node_count
        if index == len(course_order):
            results.append(list(chosen))
            return

        course = course_order[index]
        for sessions in options_by_course[course].values():
            node_count += 1
            if node_count > NODE_CAP:
                return
            if any(_sessions_overlap(s, a) for s in sessions for a in assigned):
                continue
            backtrack(index + 1, assigned + sessions, chosen + sessions)

    backtrack(0, [], [])
    return results


def _find_pairwise_conflicts(
    course_order: list[str],
    options_by_course: dict[str, dict[str, list[ClassSession]]],
) -> list[tuple[str, str]]:
    conflicts = []
    for i in range(len(course_order)):
        for j in range(i + 1, len(course_order)):
            course_a, course_b = course_order[i], course_order[j]
            compatible = any(
                not _group_conflicts(opt_a, opt_b)
                for opt_a in options_by_course[course_a].values()
                for opt_b in options_by_course[course_b].values()
            )
            if not compatible:
                conflicts.append((course_a, course_b))
    return conflicts


def _score_timetable(sessions: list[ClassSession], prefs: Preferences) -> tuple[float, dict[str, float]]:
    breakdown: dict[str, float] = defaultdict(float)
    by_day: dict[str, list[ClassSession]] = defaultdict(list)
    preferred_group_keys = {(g.course_code, g.group_number) for g in prefs.preferred_groups}

    for s in sessions:
        by_day[s.day].append(s)

        if s.instructor_name and s.instructor_name in prefs.preferred_instructors:
            breakdown["preferred_instructor"] += WEIGHTS["preferred_instructor"]

        if (s.course_code, s.group_number) in preferred_group_keys:
            breakdown["preferred_group"] += WEIGHTS["preferred_group"]

        if s.day in prefs.preferred_days:
            breakdown["preferred_day"] += WEIGHTS["preferred_day"]

        start_min = _time_to_minutes(s.time_start)
        end_min = _time_to_minutes(s.time_end)

        if prefs.avoid_early and start_min < EARLY_THRESHOLD_MIN:
            breakdown["avoid_early"] -= WEIGHTS["avoid_early_per_min"] * (EARLY_THRESHOLD_MIN - start_min)

        if prefs.avoid_late and end_min > LATE_THRESHOLD_MIN:
            breakdown["avoid_late"] -= WEIGHTS["avoid_late_per_min"] * (end_min - LATE_THRESHOLD_MIN)

    for day in prefs.free_days:
        if day not in by_day:
            breakdown["free_day"] += WEIGHTS["free_day_bonus"]

    if prefs.minimize_gaps:
        total_gap = 0
        for day_sessions in by_day.values():
            ordered = sorted(day_sessions, key=lambda s: _time_to_minutes(s.time_start))
            for a, b in zip(ordered, ordered[1:]):
                gap = _time_to_minutes(b.time_start) - _time_to_minutes(a.time_end)
                if gap > 0:
                    total_gap += gap
        if total_gap:
            breakdown["gaps"] -= WEIGHTS["gap_penalty_per_min"] * total_gap

    if prefs.compact:
        breakdown["compactness"] -= WEIGHTS["compactness_penalty_per_day"] * len(by_day)

    total = sum(breakdown.values())
    return total, dict(breakdown)


def generate_timetables(request: GenerateRequest) -> GenerateResponse:
    hc = request.hard_constraints
    prefs = request.preferences
    selected = request.selected_courses

    blocked_instructors = set(hc.blocked_instructors)
    blocked_days = set(hc.blocked_days)

    def _hits_day_or_time_block(s: ClassSession) -> bool:
        if s.day in blocked_days:
            return True
        return any(
            s.day == tr.day and _ranges_overlap(s.time_start, s.time_end, tr.start, tr.end)
            for tr in hc.blocked_time_ranges
        )

    # A course's lecture and tutorial share one group and are always taken
    # together, often on different days with different instructors. So ANY
    # hard constraint that would exclude one of those two sessions -- a
    # blocked instructor, a blocked day, or a blocked time range -- has to
    # exclude their WHOLE group, not just the one session that triggered it.
    # Filtering session-by-session (as this used to) could silently strip a
    # group down to just its tutorial (or just its lecture) and still hand
    # that incomplete group to the solver as a normal, valid option.
    blocked_section_keys = {(g.course_code, g.group_number) for g in hc.blocked_sections}
    for s in request.classes:
        if s.course_code not in selected:
            continue
        if (
            (s.instructor_name and s.instructor_name in blocked_instructors)
            or _hits_day_or_time_block(s)
        ):
            blocked_section_keys.add((s.course_code, s.group_number))

    def is_blocked(s: ClassSession) -> bool:
        return (s.course_code, s.group_number) in blocked_section_keys

    filtered = [s for s in request.classes if s.course_code in selected and not is_blocked(s)]

    options_by_course: dict[str, dict[str, list[ClassSession]]] = defaultdict(lambda: defaultdict(list))
    for s in filtered:
        options_by_course[s.course_code][s.group_number].append(s)

    missing = [
        CourseConflict(
            course_code=course,
            reason="No available sections remain for this course after applying your hard constraints "
            "(or the course wasn't found in the uploaded data).",
        )
        for course in selected
        if not options_by_course.get(course)
    ]
    if missing:
        return GenerateResponse(status="unsatisfiable", conflicts=missing)

    course_order = sorted(selected, key=lambda c: len(options_by_course[c]))
    raw_results = _backtrack_search(course_order, options_by_course)

    if not raw_results:
        pairwise = _find_pairwise_conflicts(course_order, options_by_course)
        if pairwise:
            conflicts = [
                CourseConflict(
                    course_code=course_a,
                    reason=f"{course_a} and {course_b} have no combination of sections that avoid overlapping each other.",
                )
                for course_a, course_b in pairwise
            ]
        else:
            conflicts = [
                CourseConflict(
                    course_code="",
                    reason="No valid combination of sections avoids all overlaps, even though no single pair of "
                    "courses is fully incompatible. Try relaxing a blocked day/time or section.",
                )
            ]
        return GenerateResponse(status="unsatisfiable", conflicts=conflicts)

    results: list[TimetableResult] = []
    for sessions in raw_results:
        total, breakdown = _score_timetable(sessions, prefs)
        days_used = sorted({s.day for s in sessions}, key=_day_sort_key)
        results.append(
            TimetableResult(
                sessions=sessions,
                score=round(total, 2),
                score_breakdown={k: round(v, 2) for k, v in breakdown.items()},
                days_used=days_used,
                total_courses=len(selected),
                total_sessions=len(sessions),
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return GenerateResponse(status="ok", results=results[: request.top_n])
