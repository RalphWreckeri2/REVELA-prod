"""Inspection report and lifecycle event both store the same remarks in VARCHAR(255).

Validate the *final* text, including any client-generated notice prefix. MySQL
VARCHAR counts characters; do not truncate evidence or alter the submitted text.
"""

MAX_INSPECTION_REMARKS_CHARACTERS = 255


class InspectionNotesInvalid(ValueError):
    pass


def validate_inspection_notes(notes):
    if notes is not None and not isinstance(notes, str):
        raise InspectionNotesInvalid("Inspection notes must be text.")
    if notes is not None and len(notes) > MAX_INSPECTION_REMARKS_CHARACTERS:
        raise InspectionNotesInvalid(
            f"Inspection notes, including any notice prefix, must be {MAX_INSPECTION_REMARKS_CHARACTERS} characters or fewer.")
    return notes
