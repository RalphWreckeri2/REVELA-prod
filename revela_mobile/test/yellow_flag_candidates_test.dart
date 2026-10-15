import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:revela_mobile/component/yellow_flag_location_picker.dart';
import 'package:revela_mobile/service/flag_service.dart';
import 'package:revela_mobile/service/inspection_service.dart';
import 'package:revela_mobile/service/yellow_flag_candidates.dart';

InspectionTask _task({
  int reportId = 100,
  int? cycleId = 2,
  int logId = 20,
  String name = 'Corner Store',
  String flag = 'Yellow',
  double? latitude = 14,
  double? longitude = 121,
}) => InspectionTask(
  reportID: reportId,
  assignmentCycleID: cycleId,
  logID: logId,
  detectedName: name,
  barangayName: 'Poblacion',
  flagColor: flag,
  verificationStatus: 'Assigned',
  latitude: latitude,
  longitude: longitude,
  irTimestamp: '2026-10-13T00:00:00Z',
);

MyFlag _flag({
  int logId = 300,
  String name = 'Corner Store',
  String color = 'Yellow',
  String? status = 'Assigned',
  double latitude = 14,
  double longitude = 121,
}) => MyFlag(
  logID: logId,
  detectedName: name,
  lat: latitude,
  lng: longitude,
  flagColor: color,
  verificationStatus: status,
);

void main() {
  group('Yellow flag candidate identities and eligibility', () {
    test('assigned Yellow tasks keep report and cycle identity', () {
      final task = _task(reportId: 91, cycleId: 4);
      final candidates = buildYellowFlagCandidates(tasks: [task], flags: []);

      expect(candidates, hasLength(1));
      expect(candidates.single.stableIdentity, 'task:${task.assignmentKey}');
      expect(candidates.single.task, same(task));
      expect(candidates.single.position, const LatLng(14, 121));
      expect(candidates.single.locationDetail, contains('Cycle 4'));
    });

    test('same-name businesses remain separate by stable identity', () {
      final first = _task(reportId: 91, cycleId: 4, name: 'Same Name');
      final second = _task(reportId: 92, cycleId: 4, name: 'Same Name');
      final candidates = buildYellowFlagCandidates(
        tasks: [first, second],
        flags: [],
      );

      expect(candidates, hasLength(2));
      expect(candidates.map((candidate) => candidate.stableIdentity).toSet(), {
        'task:${first.assignmentKey}',
        'task:${second.assignmentKey}',
      });
      expect(
        candidates.map((candidate) => candidate.locationDetail).toSet(),
        hasLength(2),
      );
    });

    test(
      'submitted flags use logID and duplicate task logIDs are suppressed',
      () {
        final task = _task(logId: 55);
        final duplicate = _flag(logId: 55);
        final separate = _flag(logId: 56);
        final candidates = buildYellowFlagCandidates(
          tasks: [task],
          flags: [duplicate, separate],
        );

        expect(candidates, hasLength(2));
        expect(
          candidates.map((candidate) => candidate.stableIdentity),
          contains('flag:56'),
        );
        expect(
          candidates.map((candidate) => candidate.stableIdentity),
          isNot(contains('flag:55')),
        );
      },
    );

    test('Red and Black tasks are excluded from the Yellow selector', () {
      final candidates = buildYellowFlagCandidates(
        tasks: [
          _task(flag: 'Yellow', reportId: 1),
          _task(flag: 'Red', reportId: 2),
          _task(flag: 'Black', reportId: 3),
        ],
        flags: [_flag(color: 'Red', logId: 4)],
      );

      expect(candidates, hasLength(1));
      expect(candidates.single.task?.reportID, 1);
    });

    test(
      'inactive submitted flags are excluded, unassigned flags remain eligible',
      () {
        final candidates = buildYellowFlagCandidates(
          tasks: [],
          flags: [
            _flag(logId: 1, status: 'Completed'),
            _flag(logId: 2, status: null),
            _flag(logId: 3, status: 'Reassigned'),
          ],
        );

        expect(candidates.map((candidate) => candidate.stableIdentity), [
          'flag:2',
          'flag:3',
        ]);
      },
    );

    test('null, non-finite, and out-of-range coordinates are excluded', () {
      final candidates = buildYellowFlagCandidates(
        tasks: [
          _task(reportId: 1, latitude: null),
          _task(reportId: 2, latitude: double.nan),
          _task(reportId: 3, longitude: double.infinity),
          _task(reportId: 4, latitude: 91),
          _task(reportId: 5, longitude: -181),
          _task(reportId: 6),
        ],
        flags: [
          _flag(logId: 7, latitude: double.nan),
          _flag(logId: 8, longitude: double.infinity),
          _flag(logId: 9, latitude: -91),
          _flag(logId: 10, longitude: 181),
        ],
      );

      expect(candidates, hasLength(1));
      expect(candidates.single.task?.reportID, 6);
    });

    test('authoritative empty data yields no candidates', () {
      expect(buildYellowFlagCandidates(tasks: [], flags: []), isEmpty);
    });

    test('failed refresh retains last-good flags for the same account', () {
      final snapshot = InMemoryYellowFlagSnapshot()
        ..selectAccount('inspector-1');
      final existing = [_flag(logId: 80)];
      snapshot.replaceAfterSuccessfulRefresh('inspector-1', existing);

      snapshot.retainAfterFailedRefresh('inspector-1');

      expect(snapshot.flags, hasLength(1));
      expect(snapshot.flags.single.logID, 80);
    });

    test('successful empty refresh clears flags authoritatively', () {
      final snapshot = InMemoryYellowFlagSnapshot()
        ..selectAccount('inspector-1')
        ..replaceAfterSuccessfulRefresh('inspector-1', [_flag(logId: 80)]);

      snapshot.replaceAfterSuccessfulRefresh('inspector-1', []);

      expect(snapshot.flags, isEmpty);
    });

    test(
      'account changes clear in-memory flags before using new account data',
      () {
        final snapshot = InMemoryYellowFlagSnapshot()
          ..selectAccount('inspector-1')
          ..replaceAfterSuccessfulRefresh('inspector-1', [_flag(logId: 80)]);

        snapshot.selectAccount('inspector-2');

        expect(snapshot.flags, isEmpty);
        expect(snapshot.accountId, 'inspector-2');
      },
    );

    test(
      'cached offline task objects remain eligible without a network dependency',
      () {
        final cached = _task(reportId: 777, cycleId: 8);
        final candidates = buildYellowFlagCandidates(
          tasks: [cached],
          flags: [],
        );

        expect(candidates.single.task, same(cached));
        expect(
          candidates.single.stableIdentity,
          'task:${cached.assignmentKey}',
        );
      },
    );
  });

  test('malformed MyFlag coordinates are not silently coerced to zero', () {
    final flag = MyFlag.fromJson({
      'logID': 900,
      'detectedName': 'Malformed',
      'latitude': 'not-a-coordinate',
      'longitude': '121.0',
      'flagColor': 'Yellow',
    });

    expect(flag.lat.isNaN, isTrue);
    expect(hasValidCoordinates(flag.lat, flag.lng), isFalse);
  });

  group('screen-space candidate selection', () {
    final first = YellowFlagCandidate.forTask(_task(reportId: 1));
    final second = YellowFlagCandidate.forTask(
      _task(reportId: 2, latitude: 14.001),
    );
    final far = YellowFlagCandidate.forTask(
      _task(reportId: 3, latitude: 14.01),
    );

    test(
      'tapped marker plus overlapping candidates are returned with tapped first',
      () {
        final result = selectNearbyYellowCandidates(
          candidates: [second, first, far, second],
          tappedIdentity: first.stableIdentity,
          projectedPoints: {
            first.stableIdentity: const YellowFlagScreenPoint(100, 100),
            second.stableIdentity: const YellowFlagScreenPoint(125, 110),
            far.stableIdentity: const YellowFlagScreenPoint(180, 100),
          },
          radiusScreenPixels: 40,
        );

        expect(result.map((candidate) => candidate.stableIdentity), [
          first.stableIdentity,
          second.stableIdentity,
        ]);
      },
    );

    test(
      'candidates outside marker-sized on-screen threshold do not group',
      () {
        final result = selectNearbyYellowCandidates(
          candidates: [first, second],
          tappedIdentity: first.stableIdentity,
          projectedPoints: {
            first.stableIdentity: const YellowFlagScreenPoint(10, 10),
            second.stableIdentity: const YellowFlagScreenPoint(51, 10),
          },
          radiusScreenPixels: 40,
        );

        expect(result, [first]);
      },
    );

    test(
      'zoom-dependent screen projection changes grouping without coordinate edits',
      () {
        final closeAtZoomedOut = selectNearbyYellowCandidates(
          candidates: [first, second],
          tappedIdentity: first.stableIdentity,
          projectedPoints: {
            first.stableIdentity: const YellowFlagScreenPoint(10, 10),
            second.stableIdentity: const YellowFlagScreenPoint(35, 10),
          },
          radiusScreenPixels: 40,
        );
        final separateAtZoomedIn = selectNearbyYellowCandidates(
          candidates: [first, second],
          tappedIdentity: first.stableIdentity,
          projectedPoints: {
            first.stableIdentity: const YellowFlagScreenPoint(10, 10),
            second.stableIdentity: const YellowFlagScreenPoint(70, 10),
          },
          radiusScreenPixels: 40,
        );

        expect(closeAtZoomedOut, hasLength(2));
        expect(separateAtZoomedIn, [first]);
        expect(first.position, const LatLng(14, 121));
        expect(second.position, const LatLng(14.001, 121));
      },
    );

    test(
      'screen threshold scales from logical pixels to native screen pixels',
      () {
        const logicalRadius = 40.0;
        const devicePixelRatio = 3.0;
        final result = selectNearbyYellowCandidates(
          candidates: [first, second],
          tappedIdentity: first.stableIdentity,
          projectedPoints: {
            first.stableIdentity: const YellowFlagScreenPoint(100, 100),
            second.stableIdentity: const YellowFlagScreenPoint(215, 100),
          },
          radiusScreenPixels: logicalRadius * devicePixelRatio,
        );

        expect(result, hasLength(2));
      },
    );

    test(
      'projection failure returns null for tapped-handler fallback',
      () async {
        final result = await projectAndSelectNearbyYellowCandidates(
          candidates: [first, second],
          tappedIdentity: first.stableIdentity,
          project: (_) async => throw Exception('projection unavailable'),
          radiusScreenPixels: 40,
        );

        expect(result, isNull);
        expect(first.task?.reportID, 1);
      },
    );

    test('missing tapped projection never guesses a different candidate', () {
      final result = selectNearbyYellowCandidates(
        candidates: [first, second],
        tappedIdentity: first.stableIdentity,
        projectedPoints: {
          second.stableIdentity: const YellowFlagScreenPoint(10, 10),
        },
        radiusScreenPixels: 40,
      );

      expect(result, isEmpty);
    });
  });

  group('candidate detail delegation and picker', () {
    test('assigned task selection dispatches exact report and cycle task', () {
      final task = _task(reportId: 91, cycleId: 5);
      final candidate = YellowFlagCandidate.forTask(task);
      InspectionTask? selectedTask;
      MyFlag? selectedFlag;

      openYellowFlagCandidate(
        candidate: candidate,
        onTask: (value) => selectedTask = value,
        onFlag: (value) => selectedFlag = value,
      );

      expect(selectedTask, same(task));
      expect(selectedTask?.assignmentKey, task.assignmentKey);
      expect(selectedFlag, isNull);
      expect(selectedTask?.verificationStatus, 'Assigned');
    });

    test('submitted flag selection dispatches its exact logID record', () {
      final flag = _flag(logId: 700);
      final candidate = YellowFlagCandidate.forFlag(flag);
      InspectionTask? selectedTask;
      MyFlag? selectedFlag;

      openYellowFlagCandidate(
        candidate: candidate,
        onTask: (value) => selectedTask = value,
        onFlag: (value) => selectedFlag = value,
      );

      expect(selectedTask, isNull);
      expect(selectedFlag, same(flag));
      expect(selectedFlag?.logID, 700);
      expect(selectedFlag?.verificationStatus, 'Assigned');
    });

    testWidgets(
      'multi-candidate picker dropdown returns the exact location selection',
      (tester) async {
        final task = YellowFlagCandidate.forTask(
          _task(reportId: 91, cycleId: 4, name: 'Same Name'),
        );
        final flag = YellowFlagCandidate.forFlag(
          _flag(logId: 501, name: 'Same Name'),
        );
        YellowFlagCandidate? selected;
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: YellowFlagLocationPicker(
                candidates: [task, flag],
                onSelected: (candidate) => selected = candidate,
              ),
            ),
          ),
        );

        expect(find.text('Select Yellow Flag Location'), findsOneWidget);
        expect(
          find.byType(DropdownButtonFormField<YellowFlagCandidate>),
          findsOneWidget,
        );
        expect(find.text('Same Name · Assigned inspection'), findsOneWidget);
        expect(find.text(task.locationDetail), findsOneWidget);

        await tester.tap(
          find.byType(DropdownButtonFormField<YellowFlagCandidate>),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Same Name · Reported flag').last);
        expect(selected, same(flag));
      },
    );
    testWidgets('same-name assigned businesses show distinct references', (
      tester,
    ) async {
      final first = YellowFlagCandidate.forTask(
        _task(reportId: 91, cycleId: 4, name: 'Same Name'),
      );
      final second = YellowFlagCandidate.forTask(
        _task(reportId: 92, cycleId: 5, name: 'Same Name'),
      );
      YellowFlagCandidate? selected;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: YellowFlagLocationPicker(
              candidates: [first, second],
              onSelected: (candidate) => selected = candidate,
            ),
          ),
        ),
      );
      await tester.tap(
        find.byType(DropdownButtonFormField<YellowFlagCandidate>),
      );
      await tester.pumpAndSettle();
      expect(find.text(first.locationDetail), findsWidgets);
      expect(find.text(second.locationDetail), findsWidgets);
      await tester.tap(find.text(second.locationDetail).last);
      expect(selected, same(second));
    });
  });
}
