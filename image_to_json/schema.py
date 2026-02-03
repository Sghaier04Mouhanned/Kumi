import json

"""
Shared schema definition for timetable extraction.

This is extracted from the notebook so that both notebooks and
standalone scripts can import and reuse the same schema.
"""

schema_dict = {
    "type": "object",
    "title": "University Timetable Extraction Schema",
    "description": "Schema for extracting structured course schedule data from university timetables.",
    "properties": {
        "group_info": {
            "type": "object",
            "title": "Group Information",
            "properties": {
                "group_number": {
                    "type": "string",
                    "description": "The academic group identifier (e.g., G1, G2, G13).",
                },
                "level": {
                    "type": "string",
                    "description": "Academic level (e.g., Sophomore, Junior, Senior).",
                },
                "academic_year": {
                    "type": "string",
                    "description": "Academic year (e.g., 2025/2026).",
                },
                "semester": {
                    "type": "string",
                    "description": "Semester identifier (e.g., S1, S2).",
                },
            },
        },
        "schedule": {
            "type": "array",
            "title": "Course Schedule",
            "description": "List of scheduled course sessions.",
            "items": {
                "type": "object",
                "properties": {
                    "course_name": {
                        "type": "string",
                        "description": "Full name of the course (e.g., Principles of Marketing).",
                    },
                    "course_code": {
                        "type": "string",
                        "description": "Official course code (e.g., BCOR 210).",
                    },
                    "course_type": {
                        "type": "string",
                        "description": "Type of course session (e.g., (L) = Lecture, Lab, (T) = Tutorial).",
                    },
                    "instructor_name": {
                        "type": "string",
                        "description": "Name of the instructor teaching the session.",
                    },
                    "class_number": {
                        "type": "string",
                        "description": "Room or class identifier (e.g., A3, A5, Lab5, S7).",
                    },
                    "day": {
                        "type": "string",
                        "description": "Day of the week (Monday to Friday).",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time slot of the session (e.g., 8:30 - 10:00).",
                    },
                },
                "required": [
                    "course_name",
                    "course_code",
                    "course_type",
                    "instructor_name",
                    "class_number",
                    "day",
                    "time",
                ],
            },
        },
    },
    "required": ["group_info", "schedule"],
}

schema_json = json.dumps(schema_dict)

