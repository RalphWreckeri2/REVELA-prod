import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:revela_mobile/service/api_config.dart';
import 'package:revela_mobile/service/auth_service.dart';

class _NoNetworkAdapter implements HttpClientAdapter {
  int requestCount = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requestCount++;
    throw StateError('Unexpected network request: ${options.uri}');
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  tearDown(ApiConfig.resetForTesting);

  test(
    'authentication client rejects a production URL before network I/O',
    () async {
      await ApiConfig.initializeForTesting(
        qaMode: true,
        qaEndpoint: 'http://10.0.2.2:5000',
      );
      final adapter = _NoNetworkAdapter();
      final service = AuthService.forTesting(
        dio: Dio(BaseOptions(baseUrl: 'https://api.revelasys.site'))
          ..httpClientAdapter = adapter,
        apiBase: 'https://api.revelasys.site',
        tokenReader: () async => null,
        clearSession: () async {},
        purgeAccount: () async {},
        clearLogoutSession: () async {},
      );

      expect(await service.getProfile(useCachedOnFailure: false), isNull);
      expect(adapter.requestCount, 0);
    },
  );
}
