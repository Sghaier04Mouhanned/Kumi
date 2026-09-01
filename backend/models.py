from pydantic import BaseModel, Field


class ClassSession(BaseModel):
    course_name: str
    course_code: str
    course_type: str | None = None
    instructor_name: str | None = None
    class_number: str | None = None
    day: str
    time: str
    group_number: str
    time_start: str
    time_end: str
    # Set only when the AI reconciliation pass auto-corrected this row, so
    # the review table can show what changed and offer an undo.
    original_course_code: str | None = None
    original_course_name: str | None = None
    original_instructor_name: str | None = None


class ExtractWarning(BaseModel):
    filename: str
    message: str


class ReconcileSuggestion(BaseModel):
    field: str  # "course" | "instructor"
    variants: list[str]
    canonical: str
    reason: str = ""


class ExtractResponse(BaseModel):
    classes: list[ClassSession]
    warnings: list[ExtractWarning] = []
    suggestions: list[ReconcileSuggestion] = []
    reconcile_note: str | None = None


class ReconcileRequest(BaseModel):
    classes: list[ClassSession]


class SharedCatalog(BaseModel):
    classes: list[ClassSession] = []
    updated_at: str | None = None
    semester_label: str | None = None


class PublishCatalogRequest(BaseModel):
    classes: list[ClassSession]
    semester_label: str | None = None
    token: str


class GroupRef(BaseModel):
    course_code: str
    group_number: str


class TimeRange(BaseModel):
    day: str
    start: str
    end: str


class HardConstraints(BaseModel):
    blocked_sections: list[GroupRef] = []
    blocked_days: list[str] = []
    blocked_time_ranges: list[TimeRange] = []


class Preferences(BaseModel):
    preferred_instructors: list[str] = []
    preferred_groups: list[GroupRef] = []
    preferred_days: list[str] = []
    free_days: list[str] = []
    avoid_early: bool = False
    avoid_late: bool = False
    minimize_gaps: bool = True
    compact: bool = True


class GenerateRequest(BaseModel):
    classes: list[ClassSession]
    selected_courses: list[str]
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    preferences: Preferences = Field(default_factory=Preferences)
    top_n: int = 3


class TimetableResult(BaseModel):
    sessions: list[ClassSession]
    score: float
    score_breakdown: dict[str, float]
    days_used: list[str]
    total_courses: int
    total_sessions: int


class CourseConflict(BaseModel):
    course_code: str
    reason: str


class GenerateResponse(BaseModel):
    status: str  # "ok" | "unsatisfiable"
    results: list[TimetableResult] = []
    conflicts: list[CourseConflict] = []
