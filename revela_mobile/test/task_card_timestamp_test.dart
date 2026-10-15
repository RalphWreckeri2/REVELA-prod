import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/inspection_service.dart';
import 'package:revela_mobile/widgets/task_card.dart';

InspectionTask _task({String? submittedAt = '2025-10-13T18:46:00Z'}) =>
    InspectionTask(
      reportID: 100,
      assignmentCycleID: 700,
      logID: 20,
      detectedName: 'Sample Shop',
      barangayName: 'Barangay II',
      flagColor: 'Yellow',
      verificationStatus: 'Submitted',
      irTimestamp: '2025-10-12T00:00:00Z',
      dispatchedAt: '2025-10-13T18:00:00Z',
      submittedAt: submittedAt,
      deadline: '2027-12-01',
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  FlutterSecureStorage.setMockInitialValues({});
  final service = InspectionService();
  tearDownAll(service.disposeForTesting);

  Future<void> showCard(
    WidgetTester tester,
    InspectionTask task, {
    bool current = false,
  }) => tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: TaskCard(task: task, isCurrent: current, onTap: () {}),
      ),
    ),
  );

  testWidgets('History separately labels dispatch and submission in Manila', (
    tester,
  ) async {
    await showCard(tester, _task());
    expect(find.text('Dispatched: Oct 14 · 2:00 AM'), findsOneWidget);
    expect(find.text('Submitted: Oct 14 · 2:46 AM'), findsOneWidget);
    expect(find.textContaining('Due '), findsNothing);
  });

  testWidgets('History does not substitute dispatch for missing submission', (
    tester,
  ) async {
    await showCard(tester, _task(submittedAt: null));
    expect(find.text('Submitted: Submission time unavailable'), findsOneWidget);
    expect(find.text('Dispatched: Oct 14 · 2:00 AM'), findsOneWidget);
  });

  testWidgets('Current Assignments retain deadline rendering', (tester) async {
    await showCard(tester, _task(), current: true);
    expect(find.text('Due Dec 1, 2027'), findsOneWidget);
    expect(find.textContaining('Dispatched:'), findsNothing);
    expect(find.textContaining('Submitted:'), findsNothing);
  });
}
