import 'dart:async';
import 'dart:io';

/// These regressions use mocked transports, never a live backend or Google API.
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  await HttpOverrides.runZoned(
    () async => await testMain(),
    createHttpClient: (_) => throw StateError(
      'Live HTTP is forbidden in the mobile regression suite. Use a mock adapter.',
    ),
  );
}
