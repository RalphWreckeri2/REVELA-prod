/// Matches the existing report and lifecycle remarks VARCHAR(255) columns.
/// The mobile notice marker and its separating space are part of this limit.
const int maxInspectionRemarksCharacters = 255;

String inspectionNoticePrefix(int noticeLevel) => switch (noticeLevel) {
  1 => '[1st Notice Issued]',
  2 => '[2nd Notice Issued]',
  3 => '[3rd Notice Issued]',
  4 => '[Escalated to Black]',
  _ => '',
};

String buildStoredInspectionNotes(String entered, int noticeLevel) {
  final text = entered.trim();
  final prefix = inspectionNoticePrefix(noticeLevel);
  if (prefix.isEmpty) return text;
  return text.isEmpty ? prefix : '$prefix $text';
}

int storedInspectionNotesLength(String entered, int noticeLevel) =>
    buildStoredInspectionNotes(entered, noticeLevel).runes.length;

int availableInspectionNoteCharacters(int noticeLevel) {
  final prefix = inspectionNoticePrefix(noticeLevel);
  return maxInspectionRemarksCharacters -
      (prefix.isEmpty ? 0 : prefix.runes.length + 1);
}
