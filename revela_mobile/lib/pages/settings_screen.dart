import 'package:revela_mobile/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import '../service/auth_service.dart';
import '../main.dart';
import '../widgets/custom_app_bar.dart';
import 'profile_page.dart';
import 'main_layout.dart';
import 'package:showcaseview/showcaseview.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _is2faEnabled = false;
  bool _biometricEnabled = true;
  bool _emailAlertsEnabled = true;
  String _themePreference = 'system';
  bool _isLoading = true;
  late PageController _pageController;

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
    _loadSettings();
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  Future<void> _loadSettings() async {
    setState(() => _isLoading = true);
    final profile = await AuthService().getProfile();
    final prefs = await SharedPreferences.getInstance();
    final String themePref = prefs.getString('theme_preference') ?? 'system';

    if (mounted) {
      setState(() {
        if (profile != null) {
          _is2faEnabled = profile['is_2fa_enabled'] == true;
          _emailAlertsEnabled = profile['emailInspectionAlerts'] == true;
        }
        _biometricEnabled = prefs.getBool('biometric_enabled') ?? false;
        _themePreference = themePref;
        _isLoading = false;
      });
    }
  }

  void _showSnackBar(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? Colors.redAccent : Colors.green,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _contactAdmin() async {
    final Uri emailLaunchUri = Uri(
      scheme: 'mailto',
      path: 'mkahoy.bplo@gmail.com',
      query: 'subject=App Support Needed',
    );

    try {
      if (await canLaunchUrl(emailLaunchUri)) {
        await launchUrl(emailLaunchUri);
      } else {
        _showSnackBar('Could not open your email app.', isError: true);
      }
    } catch (e) {
      _showSnackBar('Could not open your email app.', isError: true);
    }
  }

  Future<void> _openLegalUrl(String url) async {
    final Uri uri = Uri.parse(url);
    try {
      if (await canLaunchUrl(uri)) {
        // Consistent with login screen, open in an in-app web view
        await launchUrl(uri, mode: LaunchMode.inAppWebView);
      } else {
        _showSnackBar('Could not open the link.', isError: true);
      }
    } catch (e) {
      // In case of an error, show a generic message
      _showSnackBar(
        'An error occurred while trying to open the link.',
        isError: true,
      );
    }
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 8, top: 24),
      child: Text(
        title.toUpperCase(),
        style: TextStyle(
          color: context.adaptiveTextMid,
          fontSize: 12,
          fontWeight: FontWeight.bold,
          letterSpacing: 1.2,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: CustomAppBar(title: 'Settings', icon: Icons.settings_rounded),
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
                      children: [
                        _buildSectionHeader('Account & Security'),
                        Showcase(
                          key: MainLayout.settingsAccountTourKey,
                          title: 'Account & Security',
                          description:
                              'Manage your profile, update your password, and configure biometric login or two-factor authentication.',
                          targetPadding: const EdgeInsets.all(4),
                          child: _SettingsCard(
                            children: [
                              ListTile(
                                leading: Icon(
                                  Icons.person_outline_rounded,
                                  color: context.adaptivePrimary,
                                ),
                                title: const Text(
                                  'Edit Profile',
                                  style: TextStyle(fontWeight: FontWeight.w600),
                                ),
                                subtitle: const Text(
                                  'Update your name and email',
                                ),
                                trailing: Icon(
                                  Icons.chevron_right,
                                  color: context.adaptiveTextLight,
                                ),
                                onTap: () {
                                  Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                      builder: (_) => const ProfilePage(),
                                    ),
                                  );
                                },
                              ),
                              Divider(
                                height: 1,
                                indent: 56,
                                color: context.adaptiveBorder,
                              ),
                              ListTile(
                                leading: Icon(
                                  Icons.lock_person_outlined,
                                  color: context.adaptivePrimary,
                                ),
                                title: const Text(
                                  'Change Password',
                                  style: TextStyle(fontWeight: FontWeight.w600),
                                ),
                                subtitle: const Text(
                                  'Update your account password',
                                ),
                                trailing: Icon(
                                  Icons.chevron_right,
                                  color: context.adaptiveTextLight,
                                ),
                                onTap: () => _showChangePasswordDialog(context),
                              ),
                              Divider(
                                height: 1,
                                indent: 56,
                                color: context.adaptiveBorder,
                              ),
                              SwitchListTile(
                                secondary: Icon(
                                  Icons.security_rounded,
                                  color: context.adaptivePrimary,
                                ),
                                title: const Text(
                                  'Two-Factor Authentication',
                                  style: TextStyle(fontWeight: FontWeight.w600),
                                ),
                                subtitle: const Text(
                                  'Add an extra layer of security',
                                ),
                                value: _is2faEnabled,
                                activeThumbColor: context.adaptivePrimary,
                                onChanged: _handle2FAChange,
                              ),
                              Divider(
                                height: 1,
                                indent: 56,
                                color: context.adaptiveBorder,
                              ),
                              SwitchListTile(
                                secondary: Icon(
                                  Icons.fingerprint_rounded,
                                  color: context.adaptivePrimary,
                                ),
                                title: const Text(
                                  'Biometric Login',
                                  style: TextStyle(fontWeight: FontWeight.w600),
                                ),
                                subtitle: const Text(
                                  'Use Face ID or Fingerprint to log in',
                                ),
                                value: _biometricEnabled,
                                activeThumbColor: context.adaptivePrimary,
                                onChanged: (bool value) async {
                                  final prefs =
                                      await SharedPreferences.getInstance();

                                  if (value) {
                                    final authService = AuthService();
                                    final hasCreds = await authService
                                        .hasSavedCredentials();
                                    if (!hasCreds) {
                                      _showSnackBar(
                                        'Cannot enable biometric login: no saved credentials found. Please log in at least once with your email and password first.',
                                        isError: true,
                                      );
                                      return;
                                    }

                                    final canUse = await authService
                                        .canUseBiometrics();
                                    if (!canUse) {
                                      _showSnackBar(
                                        'Cannot enable biometric login: this device does not support biometrics or none are enrolled.',
                                        isError: true,
                                      );
                                      return;
                                    }

                                    // User is trying to enable biometrics
                                    final authSuccess = await authService
                                        .authenticateForSetup();
                                    if (!authSuccess) {
                                      // If they cancel or fail, don't enable it
                                      _showSnackBar(
                                        'Biometric authentication failed. Cannot enable.',
                                        isError: true,
                                      );
                                      return;
                                    }
                                  }

                                  await prefs.setBool(
                                    'biometric_enabled',
                                    value,
                                  );
                                  setState(() => _biometricEnabled = value);
                                  _showSnackBar(
                                    value
                                        ? 'Biometric login enabled'
                                        : 'Biometric login disabled',
                                  );
                                },
                              ),
                            ],
                          ),
                        ),

                        _buildSectionHeader('Preferences'),
                        Showcase(
                          key: MainLayout.settingsPreferencesTourKey,
                          title: 'Preferences',
                          description:
                              'Toggle email alerts and customize the app appearance (Light/Dark mode).',
                          targetPadding: const EdgeInsets.all(4),
                          child: _SettingsCard(
                            children: [
                              SwitchListTile(
                                secondary: Icon(
                                  Icons.alternate_email_rounded,
                                  color: context.adaptivePrimary,
                                ),
                                title: const Text(
                                  'Email Inspection Alerts',
                                  style: TextStyle(fontWeight: FontWeight.w600),
                                ),
                                subtitle: const Text(
                                  'Receive emails when assigned a new inspection',
                                ),
                                value: _emailAlertsEnabled,
                                activeThumbColor: context.adaptivePrimary,
                                onChanged: (bool value) async {
                                  setState(() => _emailAlertsEnabled = value);
                                  final success = await AuthService()
                                      .updateEmailAlerts(value);
                                  if (!success) {
                                    setState(
                                      () => _emailAlertsEnabled = !value,
                                    );
                                    _showSnackBar(
                                      'We couldn\'t save your preference. Please try again.',
                                      isError: true,
                                    );
                                  } else {
                                    _showSnackBar('Preference updated');
                                  }
                                },
                              ),
                              Divider(
                                height: 1,
                                indent: 56,
                                color: context.adaptiveBorder,
                              ),
                              Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 16,
                                  vertical: 12,
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        Icon(
                                          Icons.brightness_6_outlined,
                                          color: AppColors.darkGreen,
                                        ),
                                        const SizedBox(width: 16),
                                        const Text(
                                          'Appearance',
                                          style: TextStyle(
                                            fontWeight: FontWeight.w600,
                                            fontSize: 16,
                                          ),
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: 12),
                                    SegmentedButton<String>(
                                      segments: const [
                                        ButtonSegment(
                                          value: 'light',
                                          icon: Icon(Icons.light_mode_outlined),
                                          label: Text('Light'),
                                        ),
                                        ButtonSegment(
                                          value: 'system',
                                          icon: Icon(Icons.devices_outlined),
                                          label: Text('System'),
                                        ),
                                        ButtonSegment(
                                          value: 'dark',
                                          icon: Icon(Icons.dark_mode_outlined),
                                          label: Text('Dark'),
                                        ),
                                      ],
                                      selected: {_themePreference},
                                      onSelectionChanged:
                                          (Set<String> newSelection) async {
                                            final value = newSelection.first;
                                            setState(
                                              () => _themePreference = value,
                                            );

                                            if (value == 'dark') {
                                              themeModeNotifier.value =
                                                  ThemeMode.dark;
                                            } else if (value == 'light') {
                                              themeModeNotifier.value =
                                                  ThemeMode.light;
                                            } else {
                                              themeModeNotifier.value =
                                                  ThemeMode.system;
                                            }

                                            final prefs =
                                                await SharedPreferences.getInstance();
                                            await prefs.setString(
                                              'theme_preference',
                                              value,
                                            );
                                          },
                                      style: ButtonStyle(
                                        visualDensity: VisualDensity.compact,
                                        side: WidgetStateProperty.all(
                                          BorderSide(
                                            color: context.adaptiveBorder,
                                          ),
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),

                        _buildSectionHeader('Other'),
                        Showcase(
                          key: MainLayout.settingsOtherTourKey,
                          title: 'Other Settings',
                          description:
                              'Access app instructions, view terms & conditions, and sign out.',
                          targetPadding: const EdgeInsets.all(4),
                          // This is the final item in the settings tour on
                          // compact devices, so keep it in the viewport.
                          enableAutoScroll: true,
                          scrollAlignment: 0.2,
                          child: Column(
                            children: [
                              _SettingsCard(
                                children: [
                                  ListTile(
                                    leading: Icon(
                                      Icons.menu_book_rounded,
                                      color: context.adaptivePrimary,
                                    ),
                                    title: const Text(
                                      'App Instructions',
                                      style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    trailing: Icon(
                                      Icons.chevron_right,
                                      color: context.adaptiveTextLight,
                                    ),
                                    onTap: () async {
                                      final prefs =
                                          await SharedPreferences.getInstance();
                                      await prefs.remove(
                                        'has_seen_tour_dashboard',
                                      );
                                      await prefs.remove('has_seen_tour_map');
                                      await prefs.remove('has_seen_tour_tasks');
                                      await prefs.remove(
                                        'has_seen_tour_notifications',
                                      );
                                      await prefs.remove(
                                        'has_seen_tour_settings',
                                      );
                                      if (!context.mounted) return;
                                      ScaffoldMessenger.of(
                                        context,
                                      ).showSnackBar(
                                        SnackBar(
                                          content: const Text(
                                            'Tours reset! Explore tabs to replay them.',
                                          ),
                                          backgroundColor:
                                              context.adaptivePrimary,
                                        ),
                                      );
                                    },
                                  ),
                                  Divider(
                                    height: 1,
                                    indent: 56,
                                    color: context.adaptiveBorder,
                                  ),
                                  ListTile(
                                    leading: Icon(
                                      Icons.gavel_rounded,
                                      color: context.adaptivePrimary,
                                    ),
                                    title: const Text(
                                      'Terms & Conditions',
                                      style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    trailing: Icon(
                                      Icons.chevron_right,
                                      color: context.adaptiveTextLight,
                                    ),
                                    onTap: () => _openLegalUrl(
                                      'https://ralphwreckeri2.github.io/revela_tc/',
                                    ),
                                  ),
                                  Divider(
                                    height: 1,
                                    indent: 56,
                                    color: context.adaptiveBorder,
                                  ),
                                  ListTile(
                                    leading: Icon(
                                      Icons.privacy_tip_outlined,
                                      color: context.adaptivePrimary,
                                    ),
                                    title: const Text(
                                      'Privacy Policy',
                                      style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    trailing: Icon(
                                      Icons.chevron_right,
                                      color: context.adaptiveTextLight,
                                    ),
                                    onTap: () => _openLegalUrl(
                                      'https://ralphwreckeri2.github.io/revela_pn/',
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 24),
                              _SettingsCard(
                                children: [
                                  ListTile(
                                    leading: Icon(
                                      Icons.info_outline,
                                      color: context.adaptivePrimary,
                                    ),
                                    title: const Text(
                                      'About REVELA',
                                      style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    subtitle: const Text(
                                      'App version and details',
                                    ),
                                    trailing: Icon(
                                      Icons.chevron_right,
                                      color: context.adaptiveTextLight,
                                    ),
                                    onTap: () {
                                      showAboutDialog(
                                        context: context,
                                        applicationName: 'REVELA Mobile',
                                        applicationVersion: '1.0.0',
                                        applicationLegalese: '© 2026 REVELA',
                                      );
                                    },
                                  ),
                                  Divider(
                                    height: 1,
                                    indent: 56,
                                    color: context.adaptiveBorder,
                                  ),
                                  ListTile(
                                    leading: Icon(
                                      Icons.support_agent_rounded,
                                      color: context.adaptivePrimary,
                                    ),
                                    title: const Text(
                                      'Contact Admin',
                                      style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    subtitle: const Text(
                                      'Get help from app support',
                                    ),
                                    trailing: Icon(
                                      Icons.chevron_right,
                                      color: context.adaptiveTextLight,
                                    ),
                                    onTap: _contactAdmin,
                                  ),
                                ],
                              ),

                              const SizedBox(height: 24),
                              _SettingsCard(
                                // Log Out Card
                                danger: true,
                                children: [
                                  ListTile(
                                    leading: Icon(
                                      Icons.logout,
                                      color: Colors.redAccent,
                                    ),
                                    title: const Text(
                                      'Log Out',
                                      style: TextStyle(
                                        color: Colors.redAccent,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    onTap: () async {
                                      final confirm = await showDialog<bool>(
                                        context: context,
                                        builder: (ctx) => AlertDialog(
                                          backgroundColor:
                                              context.adaptiveSurface,
                                          title: const Text('Log Out'),
                                          titleTextStyle: TextStyle(
                                            color: context.adaptiveTextDark,
                                            fontSize: 20,
                                            fontWeight: FontWeight.bold,
                                          ),
                                          content: const Text(
                                            'Are you sure you want to log out?',
                                          ),
                                          contentTextStyle: TextStyle(
                                            color: context.adaptiveTextMid,
                                            fontSize: 16,
                                          ),
                                          actions: [
                                            TextButton(
                                              onPressed: () =>
                                                  Navigator.pop(ctx, false),
                                              child: Text(
                                                'Cancel',
                                                style: TextStyle(
                                                  color:
                                                      context.adaptiveTextMid,
                                                ),
                                              ),
                                            ),
                                            TextButton(
                                              onPressed: () =>
                                                  Navigator.pop(ctx, true),
                                              child: const Text(
                                                'Log Out',
                                                style: TextStyle(
                                                  fontWeight: FontWeight.bold,
                                                  color: Colors.redAccent,
                                                ),
                                              ),
                                            ),
                                          ],
                                        ),
                                      );
                                      if (confirm == true) {
                                        await AuthService().logout();
                                      }
                                    },
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
  }

  void _handle2FAChange(bool enable) async {
    if (enable) {
      final res = await AuthService().setup2FA();
      if (res == null || res['secret'] == null) {
        _showSnackBar(
          'Unable to set up Two-Factor Authentication at this time. Please try again.',
          isError: true,
        );
        return;
      }
      final String secret = res['secret'];
      final String? otpUri = res['otpUri'];
      _show2FASetupDialog(secret, otpUri);
    } else {
      final confirm = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Disable 2FA'),
          content: const Text(
            'Are you sure you want to disable Two-Factor Authentication?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Disable', style: TextStyle(color: Colors.red)),
            ),
          ],
        ),
      );

      if (confirm == true) {
        final success = await AuthService().disable2FA();
        if (success) {
          setState(() => _is2faEnabled = false);
          _showSnackBar('2FA disabled successfully');
        } else {
          _showSnackBar(
            'Unable to disable Two-Factor Authentication. Please try again.',
            isError: true,
          );
        }
      }
    }
  }

  void _show2FASetupDialog(String secret, String? otpUri) {
    final codeController = TextEditingController();
    final formKey = GlobalKey<FormState>();
    bool isSubmitting = false;
    String? errorMsg;
    final qrUrl =
        'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${Uri.encodeComponent(otpUri ?? secret)}';

    showDialog(
      context: context,
      builder: (dialogCtx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: const Text('Setup 2FA'),
              content: SingleChildScrollView(
                child: Form(
                  key: formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text(
                        'Scan this QR code with your Authenticator App (e.g. Google Authenticator):',
                        style: TextStyle(fontSize: 13),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 12),
                      Container(
                        width: 180,
                        height: 180,
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: context.adaptiveSurface,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: Colors.grey.shade300),
                        ),
                        child: Image.network(
                          qrUrl,
                          fit: BoxFit.contain,
                          loadingBuilder: (ctx, child, progress) {
                            if (progress == null) return child;
                            return const Center(
                              child: CircularProgressIndicator(),
                            );
                          },
                          errorBuilder: (ctx, err, stack) => const Center(
                            child: Icon(
                              Icons.qr_code,
                              size: 80,
                              color: Colors.grey,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Or manually enter this secret key:',
                        style: TextStyle(fontSize: 12, color: Colors.grey),
                      ),
                      const SizedBox(height: 4),
                      SelectableText(
                        secret,
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 15,
                          letterSpacing: 1.2,
                          color: Colors.blueAccent,
                        ),
                      ),
                      const SizedBox(height: 16),
                      if (errorMsg != null) ...[
                        Text(
                          errorMsg!,
                          style: const TextStyle(
                            color: Colors.red,
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: 8),
                      ],
                      TextFormField(
                        controller: codeController,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Enter 6-Digit Code *',
                          border: OutlineInputBorder(),
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
                  onPressed: () => Navigator.pop(dialogCtx),
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  onPressed: isSubmitting
                      ? null
                      : () async {
                          if (formKey.currentState!.validate()) {
                            setDialogState(() {
                              isSubmitting = true;
                              errorMsg = null;
                            });
                            final result = await AuthService().verify2FASetup(
                              codeController.text.trim(),
                            );
                            if (result['success'] == true) {
                              if (dialogCtx.mounted) {
                                Navigator.pop(dialogCtx);
                                setState(() => _is2faEnabled = true);
                                _showSnackBar('2FA enabled successfully!');
                              }
                            } else {
                              setDialogState(() {
                                isSubmitting = false;
                                errorMsg =
                                    result['error'] ?? 'Verification failed';
                              });
                            }
                          }
                        },
                  child: isSubmitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Enable'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  void _showChangePasswordDialog(BuildContext context) {
    final oldPasswordController = TextEditingController();
    final newPasswordController = TextEditingController();
    final confirmPasswordController = TextEditingController();
    final formKey = GlobalKey<FormState>();
    bool obscureOld = true;
    bool obscureNew = true;
    bool obscureConfirm = true;
    bool isSubmitting = false;
    String? errorMsg;

    showDialog(
      context: context,
      builder: (dialogCtx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: const Text('Change Password'),
              content: SingleChildScrollView(
                child: Form(
                  key: formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (errorMsg != null) ...[
                        Text(
                          errorMsg!,
                          style: const TextStyle(
                            color: Colors.red,
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: 8),
                      ],
                      TextFormField(
                        controller: oldPasswordController,
                        obscureText: obscureOld,
                        decoration: InputDecoration(
                          labelText: 'Current Password *',
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
                        validator: (val) =>
                            val != null && val.isEmpty ? 'Required' : null,
                      ),
                      const SizedBox(height: 10),
                      TextFormField(
                        controller: newPasswordController,
                        obscureText: obscureNew,
                        decoration: InputDecoration(
                          labelText: 'New Password (min. 8 chars) *',
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
                        validator: (val) {
                          if (val == null || val.isEmpty) return 'Required';
                          if (val.length < 8) {
                            return 'Must be at least 8 characters';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 10),
                      TextFormField(
                        controller: confirmPasswordController,
                        obscureText: obscureConfirm,
                        decoration: InputDecoration(
                          labelText: 'Confirm New Password *',
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
                        validator: (val) {
                          if (val != newPasswordController.text) {
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
                TextButton(
                  onPressed: () => Navigator.pop(dialogCtx),
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  onPressed: isSubmitting
                      ? null
                      : () async {
                          if (formKey.currentState!.validate()) {
                            setDialogState(() {
                              isSubmitting = true;
                              errorMsg = null;
                            });
                            final res = await AuthService().changePassword(
                              oldPasswordController.text,
                              newPasswordController.text,
                            );
                            if (res['success'] == true) {
                              if (dialogCtx.mounted) {
                                Navigator.pop(dialogCtx);
                                _showSnackBar('Password changed successfully');
                              }
                            } else {
                              setDialogState(() {
                                isSubmitting = false;
                                errorMsg =
                                    res['error'] ??
                                    'We couldn\'t update your password. Please try again.';
                              });
                            }
                          }
                        },
                  child: isSubmitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Save'),
                ),
              ],
            );
          },
        );
      },
    );
  }
}

class _SettingsCard extends StatelessWidget {
  final List<Widget> children;
  final bool danger;
  const _SettingsCard({required this.children, this.danger = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: danger
            ? (context.isDarkMode
                  ? Colors.red.withValues(alpha: 0.1)
                  : Colors.red.shade50)
            : context.adaptiveSurface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: danger
              ? (context.isDarkMode
                    ? Colors.red.withValues(alpha: 0.3)
                    : Colors.red.shade200)
              : context.adaptiveBorder,
          width: 0.8,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(mainAxisSize: MainAxisSize.min, children: children),
    );
  }
}
