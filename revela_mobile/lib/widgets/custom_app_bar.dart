import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class CustomAppBar extends StatelessWidget implements PreferredSizeWidget {
  final String title;
  final IconData? icon;
  final List<Widget>? actions;
  final bool showBackButton;

  const CustomAppBar({
    super.key,
    required this.title,
    this.icon,
    this.actions,
    this.showBackButton = true,
  });

  @override
  Widget build(BuildContext context) {
    final canPop = Navigator.of(context).canPop();
    final shouldShowBack = showBackButton && canPop;

    return AppBar(
      toolbarHeight: 80,
      backgroundColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleSpacing: shouldShowBack ? 0 : 24,
      leading: shouldShowBack
          ? IconButton(
              icon: Icon(Icons.arrow_back_ios_new_rounded, color: context.adaptiveTextDark),
              onPressed: () => Navigator.pop(context),
            )
          : null,
      title: Row(
        children: [
          if (icon != null) ...[
            Icon(icon, color: context.isDarkMode ? Colors.white : AppColors.darkGreen, size: 32),
            const SizedBox(width: 12),
          ],
          Expanded(
            child: Text(
              title,
              style: TextStyle(
                color: context.adaptiveTextDark,
                fontWeight: FontWeight.bold,
                fontSize: 28,
                letterSpacing: -0.5,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
      actions: actions,
    );
  }

  @override
  Size get preferredSize => const Size.fromHeight(80);
}
