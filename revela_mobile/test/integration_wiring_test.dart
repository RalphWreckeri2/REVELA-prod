import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  String source(String path) => File(path).readAsStringSync();
  const nativeRoot = 'android/app/src/main/kotlin/ph/gov/mataasnakahoy/revela';

  test('map retains exactly one pair of zoom controls', () {
    final home = source('lib/pages/home_page.dart');
    expect("tooltip: 'Zoom In'".allMatches(home), hasLength(1));
    expect("tooltip: 'Zoom Out'".allMatches(home), hasLength(1));
    expect(home, contains('zoomControlsEnabled: false'));
  });

  test('walking directions and unused WIP helpers stay excluded', () {
    for (final path in [
      'lib/pages/home_page.dart',
      'lib/component/inspection_modal.dart',
    ]) {
      final contents = source(path);
      expect(contents, isNot(contains('WalkingRoute')));
      expect(contents, isNot(contains('onWalkingDirections')));
      expect(contents, isNot(contains('walking_route_service')));
    }
    for (final path in [
      'lib/service/walking_route_service.dart',
      'lib/component/yellow_flag_pin_picker.dart',
      'lib/service/legal_policy_urls.dart',
    ]) {
      expect(File(path).existsSync(), isFalse, reason: path);
    }
  });

  test('Street View native registration and Dart channels match', () {
    final activity = source('$nativeRoot/MainActivity.kt');
    final nativeView = source('$nativeRoot/StreetViewPanoramaPlatformView.kt');
    final screen = source('lib/pages/street_view_screen.dart');
    expect(activity, contains('StreetViewPanoramaFactory.VIEW_TYPE'));
    expect(nativeView, contains('"revela/streetview-panorama"'));
    expect(screen, contains("'revela/streetview-panorama'"));
    expect(nativeView, contains('"revela/streetview/\$viewId"'));
    expect(screen, contains("'revela/streetview/\$id'"));
    expect(nativeView, contains('StreetViewSource.OUTDOOR'));
    expect(
      screen,
      contains("'Street View is currently available on Android only.'"),
    );
  });

  test(
    'client build identity uses the matching native configuration channel',
    () {
      final activity = source('$nativeRoot/MainActivity.kt');
      final runtime = source('lib/service/runtime_build_config.dart');
      final gradle = source('android/app/build.gradle.kts');
      final qaManifest = source('android/app/src/qa/AndroidManifest.xml');
      expect(activity, contains('"revela/build_config"'));
      expect(activity, contains('"getBuildConfig"'));
      expect(runtime, contains("'revela/build_config'"));
      expect(runtime, contains("'getBuildConfig'"));
      expect(gradle, contains('applicationIdSuffix = ".qa"'));
      expect(qaManifest, contains('android:name="revela.qa_api_base"'));
      expect(qaManifest, contains('tools:node="remove"'));
      expect(gradle, contains('play-services-maps:20.0.0'));
    },
  );
}
