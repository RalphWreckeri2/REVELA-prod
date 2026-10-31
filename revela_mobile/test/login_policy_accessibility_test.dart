import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/pages/login_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Finder richTextContaining(String text) => find.byWidgetPredicate((widget) {
    if (widget is Text) {
      return (widget.data ?? widget.textSpan?.toPlainText() ?? '').contains(
        text,
      );
    }
    return widget is RichText && widget.text.toPlainText().contains(text);
  });

  Future<void> pumpLogin(
    WidgetTester tester, {
    required Brightness brightness,
  }) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(brightness: brightness),
        home: const LoginPage(),
      ),
    );
    await tester.pumpAndSettle();
  }

  test(
    'bundled policy documents contain their complete closing sections',
    () async {
      final terms = await rootBundle.loadString('assets/legal/terms.md');
      final privacy = await rootBundle.loadString('assets/legal/privacy.md');
      final cookies = await rootBundle.loadString('assets/legal/cookies.md');

      expect(terms, contains('## 16. Governing Law, Jurisdiction & Inquiries'));
      expect(terms, contains('All rights reserved.'));
      expect(
        privacy,
        contains('## 9. Contact Information & Data Protection Officer'),
      );
      expect(privacy, contains('All rights reserved.'));
      expect(cookies, contains('## 7. Policy Amendments & Inquiries'));
      expect(cookies, contains('All rights reserved.'));
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'initial acknowledgment exposes all policy links in $brightness mode',
      (tester) async {
        await pumpLogin(tester, brightness: brightness);

        expect(
          find.byKey(const Key('privacy-policy-acknowledgment-link')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('terms-policy-acknowledgment-link')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('cookies-policy-acknowledgment-link')),
          findsOneWidget,
        );
        expect(find.byType(Checkbox), findsOneWidget);
        expect(find.byIcon(Icons.lock_outline_rounded), findsOneWidget);
        expect(find.byIcon(Icons.description_outlined), findsOneWidget);
        expect(find.byIcon(Icons.storage_outlined), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('privacy acknowledgment adapts to phone and tablet widths', (
    tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    for (final size in [const Size(320, 568), const Size(760, 814)]) {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = size;
      await pumpLogin(tester, brightness: Brightness.light);

      expect(find.text('Your Privacy Matters'), findsOneWidget);
      expect(
        find.byKey(const Key('privacy-policy-acknowledgment-link')),
        findsOneWidget,
      );
      expect(
        tester
            .getSize(find.byKey(const Key('privacy-policy-dialog-card')))
            .height,
        lessThan(size.height * 0.9),
      );
      expect(tester.takeException(), isNull);
    }
  });

  testWidgets('cookie policy opens as a local native scrollable screen', (
    tester,
  ) async {
    await pumpLogin(tester, brightness: Brightness.light);

    await tester.tap(
      find.byKey(const Key('cookies-policy-acknowledgment-link')),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 50)),
    );
    await tester.pump();

    expect(find.text('Cookie & Storage Policy'), findsOneWidget);
    expect(find.text('Cookie & Web Storage Policy'), findsOneWidget);
    await tester.drag(find.byType(ListView), const Offset(0, -500));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('1. Understanding Cookies & Web Storage'), findsOneWidget);
    expect(find.byType(ListView), findsOneWidget);

    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));
    final preferences = await SharedPreferences.getInstance();
    expect(preferences.getString('privacy_policy_accepted_version'), isNull);
    expect(find.text('Your Privacy Matters'), findsOneWidget);
    expect(tester.widget<Checkbox>(find.byType(Checkbox)).value, isFalse);
  });

  testWidgets('Terms and Privacy links open their local policy content', (
    tester,
  ) async {
    await pumpLogin(tester, brightness: Brightness.light);

    await tester.tap(
      find.byKey(const Key('privacy-policy-acknowledgment-link')),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 50)),
    );
    await tester.pump();
    expect(find.text('Privacy Policy for REVELA'), findsOneWidget);
    expect(
      richTextContaining('This Privacy Policy sets forth how the Municipality'),
      findsWidgets,
    );

    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.byKey(const Key('terms-policy-acknowledgment-link')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 50)),
    );
    await tester.pump();
    expect(find.text('Terms and Conditions for REVELA'), findsOneWidget);
    expect(
      richTextContaining('Welcome to REVELA ("the Service")'),
      findsWidgets,
    );
  });

  testWidgets(
    'existing checkbox alone enables and records version 1.0 acceptance',
    (tester) async {
      await pumpLogin(tester, brightness: Brightness.light);

      final continueButton = tester.widget<ElevatedButton>(
        find.widgetWithText(ElevatedButton, 'Continue'),
      );
      expect(continueButton.onPressed, isNull);

      await tester.tap(find.byType(Checkbox));
      await tester.pumpAndSettle();
      expect(tester.widget<Checkbox>(find.byType(Checkbox)).value, isTrue);
      expect(
        tester
            .widget<ElevatedButton>(
              find.widgetWithText(ElevatedButton, 'Continue'),
            )
            .onPressed,
        isNotNull,
      );

      final continueButtonFinder = find.widgetWithText(
        ElevatedButton,
        'Continue',
      );
      await tester.ensureVisible(continueButtonFinder);
      await tester.tap(continueButtonFinder);
      await tester.pumpAndSettle();

      final preferences = await SharedPreferences.getInstance();
      expect(preferences.getString('privacy_policy_accepted_version'), '1.0');
      expect(preferences.getKeys(), {'privacy_policy_accepted_version'});
    },
  );
}
