import 'package:flutter/material.dart';
import 'dart:io';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter/gestures.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme/app_theme.dart';
import '../service/auth_service.dart';
import '../service/connectivity_service.dart';
import '../service/push_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'main_layout.dart';
import 'mandatory_biometric_setup_page.dart';

class LoginPage extends StatefulWidget {
  final bool accountRevokedNotice;
  const LoginPage({super.key, this.accountRevokedNotice = false});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  bool _obscurePassword = true;
  final AuthService _authService = AuthService();
  bool _isLoading = false;
  bool _canUseBiometrics = false;

  // Bump this string whenever the Privacy Policy / Terms actually change.
  // Anyone who already agreed to an older version will be prompted again.
  static const String _privacyPolicyVersion = '1.0';
  static const String _privacyPolicyAcceptedKey =
      'privacy_policy_accepted_version';

  @override
  void initState() {
    super.initState();
    // Runs after the first frame so `context` is safe to use for showDialog.
    // Biometrics auto-login is deliberately checked afterward (see
    // _checkPrivacyPolicyAcceptance) so it can't pop up at the same time as
    // the privacy dialog.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (widget.accountRevokedNotice) {
        _showAccountRevokedDialog();
      } else {
        _checkPrivacyPolicyAcceptance();
      }
    });
  }

  void _showAccountRevokedDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: const [
            Icon(Icons.remove_circle_outline_rounded, color: Colors.redAccent, size: 28),
            SizedBox(width: 8),
            Expanded(
              child: Text(
                'Access Revoked',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
        content: const Text(
          'You cannot access the application. The administrator has already removed or deactivated your account.',
          style: TextStyle(fontSize: 14, height: 1.4),
        ),
        actions: [
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.darkGreen,
              foregroundColor: Colors.white,
            ),
            child: const Text('Understood'),
          ),
        ],
      ),
    );
  }

  Future<void> _checkPrivacyPolicyAcceptance() async {
    final prefs = await SharedPreferences.getInstance();
    final acceptedVersion = prefs.getString(_privacyPolicyAcceptedKey);

    if (acceptedVersion == _privacyPolicyVersion) {
      // Already agreed to the current version — proceed as normal.
      _checkBiometrics();
      return;
    }

    // No stored acceptance = first-time user. A stored-but-different
    // version = the policy changed since they last agreed.
    final isUpdate = acceptedVersion != null;
    if (mounted) _showPrivacyPolicyDialog(isUpdate: isUpdate);
  }

  void _showPrivacyPolicyDialog({required bool isUpdate}) {
    bool isChecked = false;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        return PopScope(
          canPop: false, // Block back-button/gesture dismissal
          child: StatefulBuilder(
            builder: (context, setDialogState) {
              return AlertDialog(
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
                title: Row(
                  children: [
                    Icon(
                      Icons.privacy_tip_rounded,
                      color: AppColors.darkGreen,
                      size: 28,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        isUpdate
                            ? 'Our Privacy Policy Has Been Updated'
                            : 'Your Privacy Matters',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
                content: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        isUpdate
                            ? 'We\'ve made changes to our Privacy Policy. Please review them before continuing to use the app.'
                            : 'Before you get started, please take a moment to review how we collect, use, and protect your data.',
                        style: const TextStyle(fontSize: 14, height: 1.4),
                      ),
                      const SizedBox(height: 16),
                      InkWell(
                        onTap: () => _openLegalUrl(
                          'https://ralphwreckeri2.github.io/revela_pn/',
                        ),
                        child: Text(
                          'Read the full Privacy Policy',
                          style: TextStyle(
                            fontSize: 14,
                            color: AppColors.darkGreen,
                            fontWeight: FontWeight.bold,
                            decoration: TextDecoration.underline,
                          ),
                        ),
                      ),
                      const SizedBox(height: 4),
                      InkWell(
                        onTap: () => _openLegalUrl(
                          'https://ralphwreckeri2.github.io/revela_tc/',
                        ),
                        child: Text(
                          'Read the Terms & Conditions',
                          style: TextStyle(
                            fontSize: 14,
                            color: AppColors.darkGreen,
                            fontWeight: FontWeight.bold,
                            decoration: TextDecoration.underline,
                          ),
                        ),
                      ),
                      const SizedBox(height: 20),
                      InkWell(
                        onTap: () => setDialogState(() {
                          isChecked = !isChecked;
                        }),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Checkbox(
                              value: isChecked,
                              activeColor: AppColors.darkGreen,
                              onChanged: (value) => setDialogState(() {
                                isChecked = value ?? false;
                              }),
                            ),
                            const Expanded(
                              child: Padding(
                                padding: EdgeInsets.only(top: 12),
                                child: Text(
                                  'I have read and agree to the Privacy '
                                  'Policy and Terms & Conditions.',
                                  style: TextStyle(fontSize: 13, height: 1.3),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                actions: [
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: isChecked
                          ? () => _acceptPrivacyPolicy(ctx)
                          : null,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.darkGreen,
                        disabledBackgroundColor: Colors.grey[300],
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                      child: const Text(
                        'Continue',
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        );
      },
    );
  }

  Future<void> _acceptPrivacyPolicy(BuildContext dialogContext) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_privacyPolicyAcceptedKey, _privacyPolicyVersion);
    if (!mounted || !dialogContext.mounted) return;
    Navigator.pop(dialogContext);
    _checkBiometrics();
  }

  Future<void> _checkBiometrics() async {
    final prefs = await SharedPreferences.getInstance();
    final isEnabledInSettings = prefs.getBool('biometric_enabled') ?? false;

    if (!isEnabledInSettings) {
      if (mounted) setState(() => _canUseBiometrics = false);
      return;
    }

    final canUse = await _authService.canUseBiometrics();
    final hasCreds = await _authService.hasSavedCredentials();
    if (mounted) {
      setState(() => _canUseBiometrics = canUse && hasCreds);
    }

    // Auto prompt if possible
    if (canUse && hasCreds) {
      // Small delay so UI renders first
      Future.delayed(const Duration(milliseconds: 500), () {
        if (mounted) _handleBiometricLogin();
      });
    }
  }

  Future<bool> _hasNetworkConnectivity({
    Duration timeout = const Duration(seconds: 2),
  }) async {
    try {
      final result = await InternetAddress.lookup(
        'example.com',
      ).timeout(timeout);
      return result.isNotEmpty && result[0].rawAddress.isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  Future<void> _showNoCachedBiometricDialog() async {
    if (!mounted) return;
    await showDialog(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          title: const Text('Offline Biometric — No Cached Profile'),
          content: const Text(
            'No locally cached profile was found for this device.\n\nPlease connect to the internet to log in.',
          ),
          actions: [
            ElevatedButton(
              onPressed: () {
                if (!mounted || !ctx.mounted) return;
                Navigator.pop(ctx);
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.darkGreen,
                foregroundColor: Colors.white,
              ),
              child: const Text('OK'),
            ),
          ],
        );
      },
    );
  }

  Future<void> _handleBiometricLogin() async {
    if (!mounted) return;
    setState(() => _isLoading = true);

    // Show which account is associated with the biometric key (if any)
    final activeProfile = await _authService.getActiveBiometricProfile();
    final hasNet = await _hasNetworkConnectivity();

    // If there is no internet connectivity, short-circuit to an offline-only
    // biometric restore flow so we do not attempt any network calls.
    if (!hasNet) {
      if (!mounted) return;
      setState(() => _isLoading = false);

      if (activeProfile != null) {
        final continueOffline = await showDialog<bool?>(
          context: context,
          barrierDismissible: false,
          builder: (ctx) {
            return AlertDialog(
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              title: const Text('Offline Login'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Logging in as ${activeProfile['fullName'] ?? 'Inspector'}',
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Text('Continue to unlock your offline session.'),
                ],
              ),
              actions: [
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: () {
                      if (!mounted || !ctx.mounted) return;
                      Navigator.pop(ctx, true);
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.darkGreen,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: const Text('Continue'),
                  ),
                ),
              ],
            );
          },
        );

        if (!mounted) return;
        if (continueOffline != true) return;
      }

      if (mounted) setState(() => _isLoading = true);
      final authenticated = await _authService.authenticateOfflineBiometric();
      if (!mounted) return;
      if (mounted) setState(() => _isLoading = false);

      bool hydrated = false;
      if (authenticated) {
        hydrated = await _authService.restoreOfflineBiometricUser();
      } else if (activeProfile != null) {
        final userId =
            activeProfile['userID']?.toString() ??
            activeProfile['id']?.toString() ??
            '';
        if (userId.isNotEmpty) {
          final pin = await _promptForPin();
          if (!mounted) return;
          if (pin != null && await _authService.verifyPin(userId, pin)) {
            hydrated = await _authService.hydrateLocalSessionForUserId(userId);
          }
        }
      }

      if (!mounted) return;
      if (hydrated) {
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (context) => const MainLayout()),
          (route) => false,
        );
        return;
      }

      await _showNoCachedBiometricDialog();
      return;
    }

    // If network is available, prefer the normal biometric flow; the service
    // will still fall back to local restore if the backend cannot be reached.
    if (activeProfile != null && mounted) {
      setState(() => _isLoading = false);
      final result = await _authService.biometricLogin();
      if (!mounted) return;
      setState(() => _isLoading = false);

      if (result == LoginResult.canceled) return;
      if (result == LoginResult.accountRevoked) {
        _showAccountRevokedDialog();
        if (mounted) _checkBiometrics();
        return;
      }
      if (result == LoginResult.failed) {
        _showErrorDialog(
          'Biometric Login Failed',
          'Your saved credentials have expired or your password was reset. Please log in manually with your new password.',
        );
        await _authService.logout();
        if (mounted) _checkBiometrics();
        return;
      }
      if (result == LoginResult.networkError) {
        await _showNoCachedBiometricDialog();
        return;
      }
      _handleLoginResult(result);
      return;
    }

    // No active profile — just attempt biometric login (online path within service)
    try {
      final result = await _authService.biometricLogin();
      if (!mounted) return;
      if (result == LoginResult.canceled) return;
      if (result == LoginResult.failed) {
        _showErrorDialog(
          'Biometric Login Failed',
          'Your saved credentials have expired or your password was reset. Please log in manually with your new password.',
        );
        await _authService.logout();
        if (mounted) _checkBiometrics();
        return;
      }
      if (result == LoginResult.networkError) {
        await _showNoCachedBiometricDialog();
        return;
      }
      _handleLoginResult(result);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _openLegalUrl(String url) async {
    final Uri uri = Uri.parse(url);
    try {
      if (await canLaunchUrl(uri)) {
        // Consistent with SettingsScreen, open in an in-app web view
        await launchUrl(uri, mode: LaunchMode.inAppWebView);
      } else {
        _showSnackBar('Could not open the link.');
      }
    } catch (e) {
      // In case of an error, show a generic message
      _showSnackBar('An error occurred while trying to open the link.');
    }
  }

  Future<String?> _promptForPin() async {
    if (!mounted) return null;
    String pin = '';
    final ok = await showDialog<bool?>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: const Text('Enter PIN'),
          content: TextField(
            keyboardType: TextInputType.number,
            obscureText: true,
            onChanged: (v) => pin = v,
            decoration: const InputDecoration(hintText: '4-digit PIN'),
          ),
          actions: [
            TextButton(
              onPressed: () {
                if (!mounted || !ctx.mounted) return;
                Navigator.pop(ctx, false);
              },
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () {
                if (!mounted || !ctx.mounted) return;
                Navigator.pop(ctx, true);
              },
              child: const Text('Unlock'),
            ),
          ],
        );
      },
    );
    if (ok == true) return pin;
    return null;
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _showSnackBar(
    String message, {
    Color backgroundColor = Colors.redAccent,
  }) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: backgroundColor,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    );
  }

  void _showErrorDialog(String title, String message) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(Icons.gpp_bad_rounded, color: Colors.redAccent, size: 28),
            SizedBox(width: 8),
            Expanded(
              child: Text(
                title,
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
        content: Text(message, style: TextStyle(fontSize: 14, height: 1.4)),
        actions: [
          TextButton(
            onPressed: () {
              if (!mounted || !ctx.mounted) return;
              Navigator.pop(ctx);
            },
            child: Text(
              'Understood',
              style: TextStyle(
                color: context.adaptivePrimary,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _handleLogin() async {
    if (!mounted) return;
    if (_emailController.text.isEmpty || _passwordController.text.isEmpty) {
      _showSnackBar('Please fill in all fields.');
      return;
    }

    setState(() => _isLoading = true);

    // ✅ Use loginWithRole instead of login
    final LoginResult result = await _authService.loginWithRole(
      _emailController.text.trim(),
      _passwordController.text,
    );

    if (!mounted) return;

    setState(() => _isLoading = false);

    _handleLoginResult(result);
  }

  void _handleLoginResult(LoginResult result) {
    final authError = _authService.lastAuthError;
    switch (result) {
      case LoginResult.success:
        _showWelcomeGreetingAndNavigate();
        break;
      case LoginResult.mustChangePassword:
        _showForcePasswordChangeDialog();
        break;
      case LoginResult.twoFactorRequired:
        _show2FALoginDialog();
        break;
      case LoginResult.notInspector:
        _showErrorDialog(
          'Unauthorized Access',
          authError ??
              'Only registered field inspectors are authorized to use the mobile application. Administrators and other personnel must log in through the web dashboard.',
        );
        break;
      case LoginResult.accountRevoked:
        _showAccountRevokedDialog();
        break;
      case LoginResult.failed:
        _showSnackBar(
          authError ?? 'Incorrect email or password. Please try again.',
        );
        break;
      case LoginResult.networkError:
        _showErrorDialog(
          'Cannot Reach Server',
          authError ??
              'Unable to connect to the server. Please check your internet connection and try again.',
        );
        break;
      case LoginResult.canceled:
        // Do nothing, user just dismissed a prompt.
        break;
    }
  }

  Future<void> _showWelcomeGreetingAndNavigate() async {
    if (!mounted) return;

    // Save FCM token to backend now that user is authenticated
    await PushNotifications.refreshFcmToken();

    // Navigate to main layout
    // Normally MyApp's auth listener performs this navigation. This fallback
    // covers a successful response that did not emit an auth-state update.
    if (mounted) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
          builder: (_) => const MainLayout(showWelcomeGreeting: true),
        ),
        (route) => false,
      );
    }
  }

  void _showForgotPasswordDialog() {
    final emailController = TextEditingController();
    bool isSubmitting = false;

    showDialog(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              title: const Text('Reset Password'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    'Enter your registered email address. Your request will be sent directly to the administrator for a secure manual reset.',
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: emailController,
                    keyboardType: TextInputType.emailAddress,
                    decoration: const InputDecoration(
                      labelText: 'Email Address',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: isSubmitting
                      ? null
                      : () {
                          if (!mounted || !ctx.mounted) return;
                          Navigator.pop(ctx);
                        },
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  onPressed: isSubmitting
                      ? null
                      : () async {
                          final email = emailController.text.trim();
                          if (email.isEmpty) {
                            _showSnackBar(
                              'Please enter your email address.',
                              backgroundColor: Colors.redAccent,
                            );
                            return;
                          }

                          setDialogState(() => isSubmitting = true);

                          final authService = AuthService();
                          await authService.requestManualPasswordReset(email);

                          if (mounted && ctx.mounted) {
                            Navigator.pop(ctx);
                            _showSnackBar(
                              'If your email is registered, the administrator has been notified.',
                              backgroundColor: Colors.green.shade600,
                            );
                          }
                        },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: context.adaptivePrimary,
                    foregroundColor: Colors.white,
                  ),
                  child: isSubmitting
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Text('Request Reset'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  void _show2FALoginDialog() {
    final codeController = TextEditingController();
    final formKey = GlobalKey<FormState>();
    bool isSubmitting = false;
    String? errorMessage;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              title: Row(
                children: [
                  Icon(
                    Icons.security,
                    color: context.adaptivePrimary,
                    size: 28,
                  ),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Two-Factor Authentication',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
              content: SingleChildScrollView(
                child: Form(
                  key: formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        'Step 2 of 2 — Enter the 6-digit code from your authenticator app to complete sign in.',
                        style: TextStyle(
                          fontSize: 13,
                          color: context.adaptiveTextMid,
                        ),
                      ),
                      SizedBox(height: 16),
                      if (errorMessage != null) ...[
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(
                            color: Colors.red.shade50,
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: Colors.red.shade200),
                          ),
                          child: Text(
                            errorMessage!,
                            style: TextStyle(color: Colors.red, fontSize: 12),
                          ),
                        ),
                        SizedBox(height: 12),
                      ],
                      TextFormField(
                        controller: codeController,
                        keyboardType: TextInputType.number,
                        autofocus: true,
                        decoration: const InputDecoration(
                          labelText: '6-Digit 2FA Code',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.pin),
                        ),
                        validator: (v) => v == null || v.length < 6
                            ? 'Enter 6-digit code'
                            : null,
                      ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () {
                    if (!mounted || !ctx.mounted) return;
                    Navigator.pop(ctx);
                  },
                  child: Text('Cancel'),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.darkGreen,
                    foregroundColor: Colors.white,
                  ),
                  onPressed: isSubmitting
                      ? null
                      : () async {
                          if (formKey.currentState!.validate()) {
                            setDialogState(() {
                              isSubmitting = true;
                              errorMessage = null;
                            });
                            final res = await _authService.verify2FALogin(
                              codeController.text.trim(),
                            );
                            if (!context.mounted || !ctx.mounted) return;
                            if (res == LoginResult.success) {
                              Navigator.pop(ctx);
                              await _authService.activateSavedUserSession();
                            } else if (res == LoginResult.mustChangePassword) {
                              Navigator.pop(ctx);
                              _showForcePasswordChangeDialog();
                            } else {
                              setDialogState(() {
                                isSubmitting = false;
                                errorMessage =
                                    'Invalid 2FA code. Please try again.';
                              });
                            }
                          }
                        },
                  child: isSubmitting
                      ? SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Text('Verify Code'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  void _showForcePasswordChangeDialog() {
    final oldController = TextEditingController(text: _passwordController.text);
    final newController = TextEditingController();
    final confirmController = TextEditingController();
    final formKey = GlobalKey<FormState>();
    bool obscureOld = true;
    bool obscureNew = true;
    bool obscureConfirm = true;
    bool isSubmitting = false;
    String? errorMessage;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              title: Row(
                children: [
                  Icon(
                    Icons.warning_amber_rounded,
                    color: Colors.orange,
                    size: 28,
                  ),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Password Change Required',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
              content: SingleChildScrollView(
                child: Form(
                  key: formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        'Your administrator requires you to update your temporary password before accessing the system.',
                        style: TextStyle(
                          fontSize: 13,
                          color: context.adaptiveTextMid,
                        ),
                      ),
                      SizedBox(height: 16),
                      if (errorMessage != null) ...[
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(
                            color: Colors.red.shade50,
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: Colors.red.shade200),
                          ),
                          child: Text(
                            errorMessage!,
                            style: TextStyle(color: Colors.red, fontSize: 12),
                          ),
                        ),
                        SizedBox(height: 12),
                      ],
                      TextFormField(
                        controller: oldController,
                        obscureText: obscureOld,
                        decoration: InputDecoration(
                          labelText: 'Temporary Password',
                          border: const OutlineInputBorder(),
                          suffixIcon: IconButton(
                            icon: Icon(
                              obscureOld
                                  ? Icons.visibility_outlined
                                  : Icons.visibility_off_outlined,
                            ),
                            onPressed: () =>
                                setDialogState(() => obscureOld = !obscureOld),
                          ),
                        ),
                        validator: (v) =>
                            v == null || v.isEmpty ? 'Required' : null,
                      ),
                      SizedBox(height: 12),
                      TextFormField(
                        controller: newController,
                        obscureText: obscureNew,
                        decoration: InputDecoration(
                          labelText: 'New Password (min. 8 chars)',
                          border: const OutlineInputBorder(),
                          suffixIcon: IconButton(
                            icon: Icon(
                              obscureNew
                                  ? Icons.visibility_outlined
                                  : Icons.visibility_off_outlined,
                            ),
                            onPressed: () =>
                                setDialogState(() => obscureNew = !obscureNew),
                          ),
                        ),
                        validator: (v) {
                          if (v == null || v.isEmpty) return 'Required';
                          if (v.length < 8) {
                            return 'Must be at least 8 characters';
                          }
                          return null;
                        },
                      ),
                      SizedBox(height: 12),
                      TextFormField(
                        controller: confirmController,
                        obscureText: obscureConfirm,
                        decoration: InputDecoration(
                          labelText: 'Confirm New Password',
                          border: const OutlineInputBorder(),
                          suffixIcon: IconButton(
                            icon: Icon(
                              obscureConfirm
                                  ? Icons.visibility_outlined
                                  : Icons.visibility_off_outlined,
                            ),
                            onPressed: () => setDialogState(
                              () => obscureConfirm = !obscureConfirm,
                            ),
                          ),
                        ),
                        validator: (v) {
                          if (v != newController.text) {
                            return 'Passwords do not match';
                          }
                          return null;
                        },
                      ),
                    ],
                  ),
                ),
              ),
              actions: [
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.darkGreen,
                    foregroundColor: Colors.white,
                  ),
                  onPressed: isSubmitting
                      ? null
                      : () async {
                          if (formKey.currentState!.validate()) {
                            setDialogState(() {
                              isSubmitting = true;
                              errorMessage = null;
                            });
                            final res = await _authService.changePassword(
                              oldController.text,
                              newController.text,
                            );
                            if (res['success'] == true) {
                              if (!context.mounted || !ctx.mounted) return;
                              final navigator = Navigator.of(context);
                              Navigator.pop(ctx);
                              await _authService.activateSavedUserSession(
                                notify: false,
                              );
                              if (!mounted) return;
                              navigator.pushReplacement(
                                MaterialPageRoute(
                                  builder: (_) => MandatoryBiometricSetupPage(
                                    email: _emailController.text.trim(),
                                  ),
                                ),
                              );
                            } else {
                              setDialogState(() {
                                isSubmitting = false;
                                errorMessage =
                                    res['error']?.toString() ??
                                    'We couldn\'t update your password. Please try again.';
                              });
                            }
                          }
                        },
                  child: isSubmitting
                      ? SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Text('Update & Continue'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.adaptivePrimary,
      body: SafeArea(
        bottom: false, // Let the white card go to the bottom
        child: ValueListenableBuilder<bool>(
          valueListenable: ConnectivityService().isOffline,
          builder: (context, isOffline, child) {
            return Column(
              children: [
                if (isOffline) const _OfflineBanner(),
                Expanded(child: child!),
              ],
            );
          },
          child: LayoutBuilder(
            builder: (context, constraints) {
              final topSpacing = (constraints.maxHeight * 0.05)
                  .clamp(16.0, 40.0)
                  .toDouble();
              final cardPadding = (constraints.maxWidth * 0.08)
                  .clamp(20.0, 32.0)
                  .toDouble();

              return SingleChildScrollView(
                keyboardDismissBehavior:
                    ScrollViewKeyboardDismissBehavior.onDrag,
                padding: EdgeInsets.only(
                  bottom: MediaQuery.viewInsetsOf(context).bottom,
                ),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: constraints.maxHeight),
                  // IntrinsicHeight gives the Column a bounded height so the
                  // Expanded dark card below can stretch all the way to the
                  // bottom of the screen instead of floating mid-page.
                  child: IntrinsicHeight(
                    child: Column(
                      children: [
                        SizedBox(height: topSpacing),
                        // Logo Container
                        Container(
                          width: 80,
                          height: 80,
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.1),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Center(
                            child: Image.asset(
                              'assets/images/logo.png',
                              height: 44,
                            ),
                          ),
                        ).animate().scale(
                          duration: 600.ms,
                          curve: Curves.easeOutBack,
                        ),

                        const SizedBox(height: 12),

                        // App Name
                        const Text(
                          'REVELA',
                          style: TextStyle(
                            fontSize: 24,
                            fontWeight: FontWeight.w900,
                            color: Colors.white,
                            letterSpacing: 4,
                          ),
                        ).animate().fadeIn(delay: 200.ms).slideY(begin: 0.2),

                        const SizedBox(height: 2),

                        // Subtitle
                        Text(
                          'Field Inspection Platform',
                          style: TextStyle(
                            fontSize: 12,
                            color: Colors.white.withValues(alpha: 0.8),
                            letterSpacing: 1.2,
                          ),
                        ).animate().fadeIn(delay: 400.ms),

                        const SizedBox(height: 24),
                        // Dark Card — Expanded so it always reaches the bottom
                        Expanded(
                          child: Container(
                            width: double.infinity,
                            padding: EdgeInsets.fromLTRB(
                              cardPadding,
                              32,
                              cardPadding,
                              32,
                            ),
                            decoration: BoxDecoration(
                              color: context.adaptiveSurface,
                              borderRadius: const BorderRadius.only(
                                topLeft: Radius.circular(32),
                                topRight: Radius.circular(32),
                              ),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Text(
                                  'Welcome',
                                  style: TextStyle(
                                    fontSize: 24,
                                    fontWeight: FontWeight.w800,
                                    color: context.adaptiveTextDark,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  'Please login to continue',
                                  style: TextStyle(
                                    fontSize: 14,
                                    color: context.adaptiveTextMid,
                                  ),
                                ),
                                const SizedBox(height: 32),

                                // Email Field
                                Text(
                                  'Email *',
                                  style: TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w700,
                                    color: context.adaptiveTextDark,
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Container(
                                  decoration: BoxDecoration(
                                    color: context.isDarkMode
                                        ? Colors.black.withValues(alpha: 0.15)
                                        : Colors.grey.shade50,
                                    borderRadius: BorderRadius.circular(12),
                                    border: Border.all(
                                      color: context.adaptiveBorder,
                                    ),
                                  ),
                                  child: TextField(
                                    style: TextStyle(
                                      color: context.adaptiveTextDark,
                                    ),
                                    controller: _emailController,
                                    keyboardType: TextInputType.emailAddress,
                                    decoration: InputDecoration(
                                      hintText: 'Enter your email',
                                      hintStyle: TextStyle(
                                        color: context.adaptiveTextLight,
                                        fontSize: 14,
                                      ),
                                      prefixIcon: Icon(
                                        Icons.email_outlined,
                                        color: context.adaptiveTextLight,
                                        size: 20,
                                      ),
                                      border: InputBorder.none,
                                      contentPadding:
                                          const EdgeInsets.symmetric(
                                            horizontal: 16,
                                            vertical: 14,
                                          ),
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 16),
                                // Password Field
                                Text(
                                  'Password *',
                                  style: TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w700,
                                    color: context.adaptiveTextDark,
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Container(
                                  decoration: BoxDecoration(
                                    color: context.isDarkMode
                                        ? Colors.black.withValues(alpha: 0.15)
                                        : Colors.grey.shade50,
                                    borderRadius: BorderRadius.circular(12),
                                    border: Border.all(
                                      color: context.adaptiveBorder,
                                    ),
                                  ),
                                  child: TextField(
                                    style: TextStyle(
                                      color: context.adaptiveTextDark,
                                    ),
                                    controller: _passwordController,
                                    obscureText: _obscurePassword,
                                    decoration: InputDecoration(
                                      hintText: 'Enter your password',
                                      hintStyle: TextStyle(
                                        color: context.adaptiveTextLight,
                                        fontSize: 14,
                                      ),
                                      prefixIcon: Icon(
                                        Icons.lock_outline,
                                        color: context.adaptiveTextLight,
                                        size: 20,
                                      ),
                                      suffixIcon: IconButton(
                                        icon: Icon(
                                          _obscurePassword
                                              ? Icons.visibility_outlined
                                              : Icons.visibility_off,
                                          color: context.adaptivePrimary,
                                          size: 20,
                                        ),
                                        onPressed: () {
                                          if (mounted) {
                                            setState(() {
                                              _obscurePassword =
                                                  !_obscurePassword;
                                            });
                                          }
                                        },
                                      ),
                                      border: InputBorder.none,
                                      contentPadding:
                                          const EdgeInsets.symmetric(
                                            horizontal: 16,
                                            vertical: 14,
                                          ),
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 12),

                                // Forgot Password Button
                                Align(
                                  alignment: Alignment.centerRight,
                                  child: TextButton(
                                    onPressed: _showForgotPasswordDialog,
                                    style: TextButton.styleFrom(
                                      foregroundColor: context.adaptivePrimary
                                          .withValues(alpha: 0.8),
                                      padding: EdgeInsets.zero,
                                      minimumSize: Size.zero,
                                      tapTargetSize:
                                          MaterialTapTargetSize.shrinkWrap,
                                    ),
                                    child: const Text(
                                      'Forgot Password?',
                                      style: TextStyle(
                                        fontSize: 13,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 24),
                                // Login Button
                                SizedBox(
                                  height: 54,
                                  child: ElevatedButton(
                                    onPressed: _isLoading ? null : _handleLogin,
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor: context.adaptivePrimary,
                                      foregroundColor: Colors.white,
                                      elevation: 0,
                                      shape: RoundedRectangleBorder(
                                        borderRadius: BorderRadius.circular(16),
                                      ),
                                    ),
                                    child: _isLoading
                                        ? const SizedBox(
                                            width: 24,
                                            height: 24,
                                            child: CircularProgressIndicator(
                                              color: Colors.white,
                                              strokeWidth: 2.5,
                                            ),
                                          )
                                        : const Row(
                                            mainAxisAlignment:
                                                MainAxisAlignment.center,
                                            children: [
                                              Text(
                                                'Login',
                                                style: TextStyle(
                                                  fontSize: 16,
                                                  fontWeight: FontWeight.w700,
                                                ),
                                              ),
                                              SizedBox(width: 8),
                                              Icon(
                                                Icons.arrow_forward_rounded,
                                                size: 20,
                                              ),
                                            ],
                                          ),
                                  ),
                                ),
                                if (_canUseBiometrics) ...[
                                  const SizedBox(height: 16),
                                  SizedBox(
                                        height: 54,
                                        child: OutlinedButton.icon(
                                          onPressed: _isLoading
                                              ? null
                                              : _handleBiometricLogin,
                                          icon: const Icon(
                                            Icons.fingerprint_rounded,
                                            size: 24,
                                          ),
                                          label: const Text(
                                            'Login with Biometrics',
                                            style: TextStyle(
                                              fontSize: 16,
                                              fontWeight: FontWeight.w700,
                                            ),
                                          ),
                                          style: OutlinedButton.styleFrom(
                                            foregroundColor:
                                                context.adaptivePrimary,
                                            side: BorderSide(
                                              color: context.adaptivePrimary
                                                  .withValues(alpha: 0.3),
                                              width: 1.5,
                                            ),
                                            shape: RoundedRectangleBorder(
                                              borderRadius:
                                                  BorderRadius.circular(16),
                                            ),
                                          ),
                                        ),
                                      )
                                      .animate()
                                      .fadeIn(delay: 600.ms)
                                      .slideY(begin: 0.1),
                                ],
                                const SizedBox(height: 24),
                                RichText(
                                  textAlign: TextAlign.center,
                                  text: TextSpan(
                                    style: TextStyle(
                                      color: context.adaptiveTextMid,
                                      fontSize: 11,
                                      height: 1.5,
                                    ),
                                    children: [
                                      const TextSpan(
                                        text:
                                            'By logging in, you agree to the ',
                                      ),
                                      TextSpan(
                                        text: 'Terms & Conditions',
                                        style: TextStyle(
                                          color: context.adaptivePrimary
                                              .withValues(alpha: 0.8),
                                          fontWeight: FontWeight.bold,
                                          decoration: TextDecoration.underline,
                                        ),
                                        recognizer: TapGestureRecognizer()
                                          ..onTap = () => _openLegalUrl(
                                            'https://ralphwreckeri2.github.io/revela_tc/',
                                          ),
                                      ),
                                      const TextSpan(text: ' and '),
                                      TextSpan(
                                        text: 'Privacy Policy',
                                        style: TextStyle(
                                          color: context.adaptivePrimary
                                              .withValues(alpha: 0.8),
                                          fontWeight: FontWeight.bold,
                                          decoration: TextDecoration.underline,
                                        ),
                                        recognizer: TapGestureRecognizer()
                                          ..onTap = () => _openLegalUrl(
                                            'https://ralphwreckeri2.github.io/revela_pn/',
                                          ),
                                      ),
                                      const TextSpan(text: '.'),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ).animate().fadeIn(delay: 500.ms).slideY(begin: 0.1),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}

/// Persistent banner shown at the top of the login screen whenever the device
/// has no connectivity, explaining that biometric unlock is still available.
class _OfflineBanner extends StatelessWidget {
  const _OfflineBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: Colors.redAccent,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: const Row(
        children: [
          Icon(Icons.wifi_off_rounded, color: Colors.white, size: 20),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              "You're offline — you can still sign in using biometrics.",
              style: TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
