import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  // Primary greens
  static const Color darkGreen = Color(0xFF1B5E20);
  static const Color midGreen = Color(0xFF2E7D32);
  static const Color lightGreen = Color(0xFF388E3C);
  static const Color paleGreen = Color(0xFFE8F5E9);

  // Accent yellow/gold
  static const Color gold = Color(0xFFFFC107);
  static const Color lightGold = Color(0xFFFFF8E1);

  // Neutrals
  static const Color white = Color(0xFFFFFFFF);
  static const Color background = Color(0xFFF4F6F4);
  static const Color textDark = Color(0xFF1A2B1A);
  static const Color textMid = Color(0xFF4A5C4A);
  static const Color textLight = Color(0xFF8A9E8A);
  static const Color borderColor = Color(0xFFD0DDD0);
}

class AppTheme {
  static ThemeData get theme {
    return ThemeData(
      useMaterial3: true,
      textTheme: GoogleFonts.interTextTheme(ThemeData.light().textTheme),
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.darkGreen,
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: AppColors.background,
    );
  }

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      textTheme: GoogleFonts.interTextTheme(ThemeData.dark().textTheme),
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.darkGreen,
        brightness: Brightness.dark,
      ),
    );
  }
}

extension ThemeContext on BuildContext {
  bool get isDarkMode => Theme.of(this).brightness == Brightness.dark;

  Color get adaptiveSurface => isDarkMode ? const Color(0xFF2C2C2C) : Colors.white;
  Color get adaptiveBackground => isDarkMode ? const Color(0xFF121212) : AppColors.background;
  Color get adaptiveTextDark => isDarkMode ? Colors.white : AppColors.textDark;
  Color get adaptiveTextMid => isDarkMode ? Colors.white70 : AppColors.textMid;
  Color get adaptiveTextLight => isDarkMode ? Colors.white54 : AppColors.textLight;
  Color get adaptiveBorder => isDarkMode ? const Color(0xFF424242) : AppColors.borderColor;
  Color get adaptivePrimary => isDarkMode ? AppColors.lightGreen : AppColors.darkGreen;
}
