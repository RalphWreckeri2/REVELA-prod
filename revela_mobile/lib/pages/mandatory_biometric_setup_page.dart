import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../theme/app_theme.dart';
import 'main_layout.dart';

class MandatoryBiometricSetupPage extends StatefulWidget {
  final String? accessToken;
  final String? email;

  const MandatoryBiometricSetupPage({
    super.key,
    this.accessToken,
    this.email,
  });

  @override
  State<MandatoryBiometricSetupPage> createState() =>
      _MandatoryBiometricSetupPageState();
}

class _MandatoryBiometricSetupPageState
    extends State<MandatoryBiometricSetupPage> {
  final LocalAuthentication _localAuth = LocalAuthentication();
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();
  bool _isAuthenticating = false;
  String? _errorMsg;

  Future<void> _enrolBiometrics() async {
    setState(() {
      _isAuthenticating = true;
      _errorMsg = null;
    });

    try {
      final bool canCheck = await _localAuth.canCheckBiometrics;
      final bool isDeviceSupported = await _localAuth.isDeviceSupported();

      if (!canCheck && !isDeviceSupported) {
        setState(() {
          _errorMsg =
              'Biometric hardware sensor (Fingerprint / Face ID) is not available on this device.';
          _isAuthenticating = false;
        });
        return;
      }

      final bool didAuthenticate = await _localAuth.authenticate(
        localizedReason:
            'Mandatory Inspector Security: Register biometrics for secure offline access.',
      );

      if (didAuthenticate) {
        if (widget.accessToken != null) {
          try {
            await _secureStorage.write(
              key: 'jwt_token',
              value: widget.accessToken,
            );
            await _secureStorage.write(
              key: 'offline_jwt_token',
              value: widget.accessToken,
            );
          } catch (e) {
            debugPrint('mandatory_biometric_setup token write error: $e');
          }
        }
        if (widget.email != null) {
          try {
            await _secureStorage.write(
              key: 'saved_email',
              value: widget.email,
            );
          } catch (e) {
            debugPrint('mandatory_biometric_setup email write error: $e');
          }
        }

        final prefs = await SharedPreferences.getInstance();
        await prefs.setBool('biometric_enabled', true);
        await prefs.setBool('onboarding_completed', true);

        if (!mounted) return;
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(
            builder: (_) => const MainLayout(showWelcomeGreeting: true),
          ),
          (route) => false,
        );
      }
    } catch (e) {
      setState(() {
        _errorMsg =
            'Biometric registration failed: ${e.toString().replaceAll('PlatformException(', '').replaceAll(')', '')}';
      });
    } finally {
      if (mounted) setState(() => _isAuthenticating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.adaptiveSurface,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Container(
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    color: context.adaptivePrimary.withValues(alpha: 0.1),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    Icons.fingerprint_rounded,
                    size: 80,
                    color: context.adaptivePrimary,
                  ),
                ),
                const SizedBox(height: 28),
                Text(
                  'Mandatory Biometric Registration',
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    color: context.adaptiveTextDark,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 12),
                Text(
                  'To protect sensitive field inspection records and enable secure offline authentication without cellular coverage, please enrol your device biometrics (Fingerprint or Face ID).',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 14,
                    color: context.adaptiveTextMid,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 32),
                if (_errorMsg != null) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red.shade50,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.red.shade200),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.error_outline, color: Colors.red),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            _errorMsg!,
                            style: const TextStyle(
                              color: Colors.red,
                              fontSize: 13,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                ],
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: ElevatedButton.icon(
                    icon: const Icon(Icons.security_rounded),
                    label: _isAuthenticating
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Text(
                            'Enrol Biometrics & Proceed',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: context.adaptivePrimary,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                    ),
                    onPressed: _isAuthenticating ? null : _enrolBiometrics,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
