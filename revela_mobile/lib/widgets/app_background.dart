import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class AppBackground extends StatelessWidget {
  final Widget child;
  const AppBackground({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    
    return Stack(
      children: [
        // Base gradient
        Container(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: isDark 
                ? [const Color(0xFF161A1D), const Color(0xFF0F1115)] 
                : [const Color(0xFFF7FBF8), const Color(0xFFE9F2EC)],
            ),
          ),
        ),
        
        // Subtle top right accent
        Positioned(
          top: -150,
          right: -100,
          child: Container(
            width: 400,
            height: 400,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(
                colors: [
                  AppColors.darkGreen.withValues(alpha: isDark ? 0.08 : 0.06),
                  Colors.transparent,
                ],
              ),
            ),
          ),
        ),
        
        // Subtle bottom left accent
        Positioned(
          bottom: -100,
          left: -150,
          child: Container(
            width: 500,
            height: 500,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(
                colors: [
                  AppColors.gold.withValues(alpha: isDark ? 0.03 : 0.04),
                  Colors.transparent,
                ],
              ),
            ),
          ),
        ),
        
        // Content
        child,
      ],
    );
  }
}
