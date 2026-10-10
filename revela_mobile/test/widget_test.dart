import 'dart:ui' show Size;

import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/main.dart';

void main() {
  testWidgets('App launches without layout exceptions at mobile sizes', (
    WidgetTester tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    const viewportSizes = [
      Size(320, 568),
      Size(360, 640),
      Size(375, 812),
      Size(390, 844),
      Size(414, 896),
    ];

    for (final size in viewportSizes) {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = size;
      await tester.pumpWidget(const MyApp());
      await tester.pump(const Duration(seconds: 5));

      expect(find.byType(MyApp), findsOneWidget);
      expect(
        tester.takeException(),
        isNull,
        reason: 'Unexpected layout exception at ${size.width}x${size.height}',
      );
    }
  });
}
