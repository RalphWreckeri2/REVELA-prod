import 'package:flutter/material.dart';

class ScaleTap extends StatefulWidget {
  final Widget child;
  final VoidCallback? onTap;
  final double scaleMinValue;
  final Duration duration;

  const ScaleTap({
    super.key,
    required this.child,
    this.onTap,
    this.scaleMinValue = 0.92,
    this.duration = const Duration(milliseconds: 150),
  });

  @override
  State<ScaleTap> createState() => _ScaleTapState();
}

class _ScaleTapState extends State<ScaleTap> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _scaleAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: widget.duration);
    _scaleAnimation = Tween<double>(begin: 1.0, end: widget.scaleMinValue).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  bool _isPressed = false;

  void _onPointerDown(PointerDownEvent event) {
    if (widget.onTap != null) {
      _isPressed = true;
      _controller.forward();
    }
  }

  void _onPointerUp(PointerUpEvent event) {
    if (widget.onTap != null) {
      _isPressed = false;
      _controller.forward().then((_) {
        if (mounted && !_isPressed) {
          _controller.reverse();
        }
      });
    }
  }

  void _onPointerCancel(PointerCancelEvent event) {
    if (widget.onTap != null) {
      _isPressed = false;
      _controller.reverse();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      onPointerDown: _onPointerDown,
      onPointerUp: _onPointerUp,
      onPointerCancel: _onPointerCancel,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: widget.onTap,
        child: AnimatedBuilder(
          animation: _controller,
          builder: (context, child) => Transform.scale(
            scale: _scaleAnimation.value,
            child: child,
          ),
          child: widget.child,
        ),
      ),
    );
  }
}
