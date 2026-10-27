import 'package:flutter/foundation.dart';

/// Opt-in CSV log lines; never logs inspector data or evidence.
class InspectionBenchmark {
  static const enabled = bool.fromEnvironment('REVELA_BENCHMARK');
  static const cache = String.fromEnvironment('REVELA_BENCHMARK_CACHE');
  static const network = String.fromEnvironment('REVELA_BENCHMARK_NETWORK');
  static const registryRows = String.fromEnvironment('REVELA_BENCHMARK_REGISTRY_ROWS');
  static const mapRows = String.fromEnvironment('REVELA_BENCHMARK_MAP_ROWS');
  static const geolocatedRows = String.fromEnvironment('REVELA_BENCHMARK_GEOLOCATED_ROWS');
  static const expectedMarkers = String.fromEnvironment('REVELA_BENCHMARK_MARKERS');
  static int _nextTrial = 0;

  static const header = 'scenario,trial,outcome,elapsed_ms,accepted_ms,visible_ms,'
      'request_id,http_status,registry_rows,map_rows,geolocated_rows,expected_markers,cache,network,'
      'evidence_files,preuploaded_urls,gps_fix,notes';

  static InspectionBenchmark? start({
    required int evidenceFiles,
    required int preuploadedUrls,
  }) {
    if (!enabled) return null;
    return InspectionBenchmark._(evidenceFiles, preuploadedUrls);
  }

  InspectionBenchmark._(this.evidenceFiles, this.preuploadedUrls)
      : trial = ++_nextTrial {
    clock.start();
  }

  final int evidenceFiles;
  final int preuploadedUrls;
  final int trial;
  final Stopwatch clock = Stopwatch();
  int? acceptedMs;
  String? requestId;
  int? httpStatus;
  bool? gpsFix;
  bool recorded = false;
  bool _duplicate = false;

  void accepted(String? id, int? status, bool duplicate) {
    acceptedMs = clock.elapsedMilliseconds;
    requestId = id;
    httpStatus = status;
    _duplicate = duplicate;
  }

  void response(String? id, int? status) {
    requestId = id;
    httpStatus = status;
  }

  void failure(String? id, int? status) => response(id, status);

  static String _csv(Object? value) =>
      '"${(value ?? '').toString().replaceAll('"', '""')}"';

  /// The outcome is only 'completed' for a confirmed new database submission.
  void finish(String outcome, {String notes = ''}) {
    if (recorded) return;
    recorded = true;
    final visible = clock.elapsedMilliseconds;
    clock.stop();
    final fields = [
      'online-inspection', trial,
      _duplicate ? 'already_accepted' :
          acceptedMs != null && outcome != 'completed' ? 'committed_local_failure' : outcome,
      visible, acceptedMs, visible, requestId, httpStatus,
      registryRows, mapRows, geolocatedRows, expectedMarkers, cache, network,
      evidenceFiles, preuploadedUrls, gpsFix, notes,
    ];
    debugPrint('REVELA_BENCHMARK_CSV,${fields.map(_csv).join(',')}');
  }
}
