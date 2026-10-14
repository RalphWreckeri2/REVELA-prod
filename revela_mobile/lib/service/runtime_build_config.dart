import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class RuntimeBuildConfig {
  RuntimeBuildConfig._();

  static const MethodChannel _channel = MethodChannel('revela/build_config');
  static bool isQa = false;
  static bool isResolved = false;
  static String? qaApiBase;
  static String? error;

  static Future<void> initialize() async {
    if (isResolved) return;
    if (defaultTargetPlatform != TargetPlatform.android) {
      isResolved = true;
      return;
    }

    try {
      final values = await _channel.invokeMapMethod<String, Object?>(
        'getBuildConfig',
      );
      final packageName = values?['packageName']?.toString();
      if (packageName == null || packageName.isEmpty) {
        throw StateError('Android build identity was not provided.');
      }
      final reportedQa = values?['qaMode'] == true;
      if (packageName.endsWith('.qa') != reportedQa) {
        throw StateError('Android package identity and QA mode disagree.');
      }
      isQa = reportedQa;
      qaApiBase = values?['qaApiBase']?.toString();
      isResolved = true;
    } catch (failure) {
      isQa = true;
      qaApiBase = null;
      error = 'Unable to verify the Android build configuration: $failure';
      isResolved = true;
      debugPrint(error);
    }
  }

  static void configureForTesting({
    required bool qaMode,
    String? apiBase,
    String? configurationError,
  }) {
    isQa = qaMode;
    qaApiBase = apiBase;
    error = configurationError;
    isResolved = true;
  }

  static void resetForTesting() {
    isQa = false;
    isResolved = false;
    qaApiBase = null;
    error = null;
  }
}
