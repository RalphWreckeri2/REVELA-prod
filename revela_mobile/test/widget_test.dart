import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/main.dart';

void main() {
  testWidgets('App launches without crashing', (WidgetTester tester) async {
    await tester.pumpWidget(const MyApp());
    expect(find.byType(MyApp), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
  });
}
