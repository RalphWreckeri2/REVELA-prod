import 'inspection_service.dart';
import 'push_notifications.dart';

/// Legacy bridge forwarding to the unified PushNotifications service.
class AssignmentNotifications {
  AssignmentNotifications._();

  static Future<void> init() async {
    await PushNotifications.initialize();
  }

  static Future<void> notifyNewAssignments({
    required List<InspectionTask> previous,
    required List<InspectionTask> next,
  }) async {
    await PushNotifications.notifyNewAssignments(
      previous: previous,
      next: next,
    );
  }

  static Future<void> notifyApproachingDeadlines(
    List<InspectionTask> tasks,
  ) async {
    await PushNotifications.notifyApproachingDeadlines(tasks);
  }
}
