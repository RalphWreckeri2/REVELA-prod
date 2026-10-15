import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/api_config.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    ApiConfig.resetForTesting();
    SharedPreferences.setMockInitialValues({
      'api_base_url': 'https://api.revelasys.site',
    });
  });

  tearDown(ApiConfig.resetForTesting);

  test('QA requires an explicit local endpoint and fails closed', () async {
    await ApiConfig.initializeForTesting(qaMode: true);

    expect(ApiConfig.isQa, isTrue);
    expect(ApiConfig.isQaReady, isFalse);
    expect(ApiConfig.apiBase, 'http://127.0.0.1:1');
    expect(ApiConfig.qaConfigurationError, contains('endpoint is missing'));
    expect(await ApiConfig.discover(), isNull);
    expect(await ApiConfig.ensureReachable(), isNull);
  });

  test('saved production URL cannot override the QA endpoint', () async {
    await ApiConfig.initializeForTesting(
      qaMode: true,
      qaEndpoint: 'http://10.0.2.2:5000',
    );

    expect(ApiConfig.apiBase, 'http://10.0.2.2:5000');
    expect(ApiConfig.isQaReady, isTrue);
    expect(
      ApiConfig.allowsRequestUri(Uri.parse('https://api.revelasys.site/api')),
      isFalse,
    );
    expect(
      ApiConfig.allowsRequestUri(Uri.parse('http://10.0.2.2:5000/api')),
      isTrue,
    );
  });

  test('QA discovery only probes the configured local endpoint', () async {
    final probed = <String>[];
    ApiConfig.probeOverride = (base) async {
      probed.add(base);
      return false;
    };
    await ApiConfig.initializeForTesting(
      qaMode: true,
      qaEndpoint: 'http://10.0.2.2:5000',
    );

    expect(await ApiConfig.discover(), isNull);
    expect(probed, ['http://10.0.2.2:5000']);
  });

  test('QA rejects production and non-local configured addresses', () async {
    for (final endpoint in [
      'https://api.revelasys.site',
      'http://8.8.8.8:5000',
      'http://10.0.2.2',
      'http://user@192.168.1.20:5000',
    ]) {
      await ApiConfig.initializeForTesting(qaMode: true, qaEndpoint: endpoint);

      expect(ApiConfig.isQaReady, isFalse, reason: endpoint);
      expect(ApiConfig.allowsRequestUri(Uri.parse(endpoint)), isFalse);
    }
  });

  test('normal app keeps its existing production API default', () async {
    SharedPreferences.setMockInitialValues({});
    await ApiConfig.initializeForTesting(qaMode: false);

    expect(ApiConfig.isQa, isFalse);
    expect(ApiConfig.apiBase, 'https://api.revelasys.site');
  });
}
