import 'package:flutter/foundation.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import 'flag_service.dart';
import 'inspection_service.dart';

enum YellowFlagRecordType { assignedTask, submittedFlag }

class YellowFlagCandidate {
  const YellowFlagCandidate._({
    required this.recordType,
    required this.stableIdentity,
    required this.displayName,
    required this.locationDetail,
    required this.position,
    this.task,
    this.flag,
  });

  factory YellowFlagCandidate.forTask(
    InspectionTask task,
  ) => YellowFlagCandidate._(
    recordType: YellowFlagRecordType.assignedTask,
    stableIdentity: 'task:${task.assignmentKey}',
    displayName: task.detectedName,
    locationDetail:
        '${task.barangayName} · Inspection #${task.reportID}'
        '${task.assignmentCycleID == null ? '' : ' · Cycle ${task.assignmentCycleID}'}',
    position: LatLng(task.latitude!, task.longitude!),
    task: task,
  );

  factory YellowFlagCandidate.forFlag(MyFlag flag) => YellowFlagCandidate._(
    recordType: YellowFlagRecordType.submittedFlag,
    stableIdentity: 'flag:${flag.logID}',
    displayName: flag.detectedName,
    locationDetail:
        'Reported flag · ${flag.verificationStatus ?? 'Pending'} · Ref ${flag.logID}',
    position: LatLng(flag.lat, flag.lng),
    flag: flag,
  );

  final YellowFlagRecordType recordType;
  final String stableIdentity;
  final String displayName;
  final String locationDetail;
  final LatLng position;
  final InspectionTask? task;
  final MyFlag? flag;

  String get typeLabel => switch (recordType) {
    YellowFlagRecordType.assignedTask => 'Assigned inspection',
    YellowFlagRecordType.submittedFlag => 'Reported flag',
  };
}

void openYellowFlagCandidate({
  required YellowFlagCandidate candidate,
  required ValueChanged<InspectionTask> onTask,
  required ValueChanged<MyFlag> onFlag,
}) {
  switch (candidate.recordType) {
    case YellowFlagRecordType.assignedTask:
      final task = candidate.task;
      if (task != null) onTask(task);
    case YellowFlagRecordType.submittedFlag:
      final flag = candidate.flag;
      if (flag != null) onFlag(flag);
  }
}

@immutable
class YellowFlagScreenPoint {
  const YellowFlagScreenPoint(this.x, this.y);

  final double x;
  final double y;
}

bool hasValidCoordinates(double? latitude, double? longitude) =>
    latitude != null &&
    longitude != null &&
    latitude.isFinite &&
    longitude.isFinite &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180;

List<YellowFlagCandidate> buildYellowFlagCandidates({
  required Iterable<InspectionTask> tasks,
  required Iterable<MyFlag> flags,
}) {
  final taskList = tasks.toList(growable: false);
  final candidates = <String, YellowFlagCandidate>{};

  for (final task in taskList) {
    if (task.flagColor != 'Yellow' ||
        !hasValidCoordinates(task.latitude, task.longitude)) {
      continue;
    }
    final candidate = YellowFlagCandidate.forTask(task);
    candidates.putIfAbsent(candidate.stableIdentity, () => candidate);
  }

  final taskLogIds = taskList.map((task) => task.logID).toSet();
  for (final flag in flags) {
    if (flag.flagColor != 'Yellow' ||
        taskLogIds.contains(flag.logID) ||
        (flag.verificationStatus != null &&
            !const {
              'Assigned',
              'Reassigned',
            }.contains(flag.verificationStatus)) ||
        !hasValidCoordinates(flag.lat, flag.lng)) {
      continue;
    }
    final candidate = YellowFlagCandidate.forFlag(flag);
    candidates.putIfAbsent(candidate.stableIdentity, () => candidate);
  }

  final result = candidates.values.toList();
  result.sort((left, right) {
    final byName = left.displayName.toLowerCase().compareTo(
      right.displayName.toLowerCase(),
    );
    if (byName != 0) return byName;
    final byDetail = left.locationDetail.toLowerCase().compareTo(
      right.locationDetail.toLowerCase(),
    );
    return byDetail != 0
        ? byDetail
        : left.stableIdentity.compareTo(right.stableIdentity);
  });
  return result;
}

List<YellowFlagCandidate> selectNearbyYellowCandidates({
  required Iterable<YellowFlagCandidate> candidates,
  required String tappedIdentity,
  required Map<String, YellowFlagScreenPoint> projectedPoints,
  required double radiusScreenPixels,
}) {
  final tappedPoint = projectedPoints[tappedIdentity];
  if (tappedPoint == null ||
      !radiusScreenPixels.isFinite ||
      radiusScreenPixels < 0) {
    return const [];
  }

  final radiusSquared = radiusScreenPixels * radiusScreenPixels;
  final unique = <String, YellowFlagCandidate>{};
  for (final candidate in candidates) {
    final point = projectedPoints[candidate.stableIdentity];
    if (point == null) continue;
    final dx = point.x - tappedPoint.x;
    final dy = point.y - tappedPoint.y;
    if (dx * dx + dy * dy <= radiusSquared) {
      unique.putIfAbsent(candidate.stableIdentity, () => candidate);
    }
  }
  final tapped = unique.remove(tappedIdentity);
  final result = unique.values.toList()
    ..sort((left, right) {
      final byName = left.displayName.toLowerCase().compareTo(
        right.displayName.toLowerCase(),
      );
      if (byName != 0) return byName;
      final byDetail = left.locationDetail.toLowerCase().compareTo(
        right.locationDetail.toLowerCase(),
      );
      return byDetail != 0
          ? byDetail
          : left.stableIdentity.compareTo(right.stableIdentity);
    });
  if (tapped != null) result.insert(0, tapped);
  return result;
}

Future<List<YellowFlagCandidate>?> projectAndSelectNearbyYellowCandidates({
  required Iterable<YellowFlagCandidate> candidates,
  required String tappedIdentity,
  required Future<YellowFlagScreenPoint> Function(LatLng) project,
  required double radiusScreenPixels,
}) async {
  final candidateList = candidates.toList(growable: false);
  final projected = <String, YellowFlagScreenPoint>{};
  try {
    for (final candidate in candidateList) {
      projected[candidate.stableIdentity] = await project(candidate.position);
    }
  } on Object catch (error) {
    debugPrint('Could not project Yellow Flag candidates: $error');
    return null;
  }
  return selectNearbyYellowCandidates(
    candidates: candidateList,
    tappedIdentity: tappedIdentity,
    projectedPoints: projected,
    radiusScreenPixels: radiusScreenPixels,
  );
}
