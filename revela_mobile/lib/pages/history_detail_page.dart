import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../service/inspection_service.dart';
import '../theme/app_theme.dart';

class HistoryDetailPage extends StatelessWidget {
  final InspectionTask? task;

  const HistoryDetailPage({super.key, this.task});

  String _formatResult(String result) {
    switch (result) {
      case 'Green': return 'Registered';
      case 'Yellow': return 'Suspected / Needs Verification';
      case 'Orange': return 'Warned / Non-Compliant';
      case 'Red': return 'Unregistered';
      case 'Black': return 'Blacklisted / Non-Responsive';
      case 'Purple': return 'Closed / Abandoned';
      default: return result;
    }
  }

  int _getNoticeLevel(InspectionTask task) {
    final remarks = task.remarks ?? '';
    final result = task.inspectionResult ?? '';
    
    if (remarks.contains('[Blacklisted/Closed]') || remarks.contains('Blacklisted') || result == 'Blacklisted/Closed') return 4;
    if (remarks.contains('[3rd Notice Issued]') || remarks.contains('Given Third Notice') || result == 'Given Third Notice') return 3;
    if (remarks.contains('[2nd Notice Issued]') || remarks.contains('Given Second Notice') || result == 'Given Second Notice') return 2;
    if (remarks.contains('[1st Notice Issued]') || remarks.contains('Given First Notice') || result == 'Given First Notice') return 1;
    
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    final InspectionTask? resolvedTask =
        task ?? ModalRoute.of(context)?.settings.arguments as InspectionTask?;

    if (resolvedTask == null) return const SizedBox();

    return DraggableScrollableSheet(
      initialChildSize: 0.85,
      minChildSize: 0.5,
      maxChildSize: 0.95,
      builder: (_, scrollController) => Container(
        decoration: BoxDecoration(
          color: context.adaptiveBackground,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
        ),
        child: Column(
          children: [
            const SizedBox(height: 12),
            Container(
              width: 40,
              height: 5,
              decoration: BoxDecoration(
                color: Colors.grey[300],
                borderRadius: BorderRadius.circular(10),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Inspection Report',
              style: TextStyle(
                color: context.adaptiveTextDark,
                fontWeight: FontWeight.bold,
                fontSize: 18,
              ),
            ),
            const SizedBox(height: 16),
            const Divider(height: 1),
            Expanded(
              child: SingleChildScrollView(
                controller: scrollController,
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
            // ── Business Card ──────────────────────────────────────────────
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: context.adaptiveSurface,
                borderRadius: BorderRadius.circular(20),
                border: context.isDarkMode ? Border.all(color: Colors.grey.shade700, width: 1) : null,
                boxShadow: [
                  BoxShadow(
                    blurRadius: 10,
                    color: Colors.black.withValues(alpha: 0.08),
                    offset: Offset(0, 4),
                  ),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 52,
                        height: 52,
                        decoration: BoxDecoration(
                          color: context.adaptivePrimary.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Icon(
                          Icons.storefront_outlined,
                          color: context.adaptivePrimary,
                          size: 28,
                        ),
                      ),
                      SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Business Name',
                              style: TextStyle(
                                fontSize: 11,
                                color: Colors.grey,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                            Text(
                              resolvedTask.detectedName,
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                                color: context.adaptiveTextDark,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const Divider(height: 28),

                  // Row: Inspector
                  FutureBuilder<String?>(
                    future: const FlutterSecureStorage().read(key: 'user_fullName'),
                    builder: (context, snapshot) {
                      return _DetailRow(
                        icon: Icons.person_outline_rounded,
                        label: 'Inspector',
                        value: snapshot.data ?? 'Field Inspector',
                      );
                    },
                  ),
                  SizedBox(height: 12),

                  // Row: Inspection Date
                  _DetailRow(
                    icon: Icons.calendar_today_outlined,
                    label: 'Inspection Date',
                    value: resolvedTask.irTimestamp,
                  ),
                  SizedBox(height: 12),

                  // Row: Address
                  _DetailRow(
                    icon: Icons.location_on_outlined,
                    label: 'Address',
                    value: resolvedTask.barangayName,
                  ),
                ],
              ),
            ),

            SizedBox(height: 20),

            // ── Inspection Details ─────────────────────────────────────────
            _SectionHeader(title: 'Inspection Details'),
            SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: context.adaptiveSurface,
                borderRadius: BorderRadius.circular(20),
                border: context.isDarkMode ? Border.all(color: Colors.grey.shade700, width: 1) : null,
                boxShadow: [
                  BoxShadow(
                    blurRadius: 10,
                    color: Colors.black.withValues(alpha: 0.08),
                    offset: Offset(0, 4),
                  ),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Status chip
                  Row(
                    children: [
                      Text(
                        'Status: ',
                        style: TextStyle(
                          color: Colors.grey,
                          fontWeight: FontWeight.w500,
                          fontSize: 13,
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 4,
                        ),
                        decoration: BoxDecoration(
                          color: resolvedTask.verificationStatus == 'Assigned'
                              ? Colors.blue.withValues(alpha: 0.1)
                              : Colors.green.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(20),
                border: context.isDarkMode ? Border.all(color: Colors.grey.shade700, width: 1) : null,
                        ),
                        child: Text(
                          resolvedTask.verificationStatus,
                          style: TextStyle(
                            color: resolvedTask.verificationStatus == 'Assigned'
                                ? Colors.blue
                                : Colors.green,
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                          ),
                        ),
                      ),
                    ],
                  ),
                  SizedBox(height: 16),

                  if (resolvedTask.inspectionResult != null &&
                      resolvedTask.inspectionResult!.isNotEmpty) ...[
                    Text(
                      'Recorded result',
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 13,
                        color: context.adaptiveTextDark,
                      ),
                    ),
                    SizedBox(height: 8),
                    Text(
                      _formatResult(resolvedTask.inspectionResult!),
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    SizedBox(height: 16),
                  ],

                  Builder(builder: (context) {
                    final noticeLevel = _getNoticeLevel(resolvedTask);
                    if (noticeLevel == 0) return const SizedBox();
                    
                    Color bgColor;
                    Color borderColor;
                    Color iconColor;
                    String title;
                    String desc;
                    IconData icon;
                    
                    if (noticeLevel == 2) {
                      bgColor = context.isDarkMode ? Colors.deepOrange.withValues(alpha: 0.1) : Colors.deepOrange.shade50;
                      borderColor = context.isDarkMode ? Colors.deepOrange.withValues(alpha: 0.3) : Colors.deepOrange.shade300;
                      iconColor = Colors.deepOrange;
                      title = 'Given Second Notice';
                      desc = 'Second official compliance notice (Warning for Closure) was issued.';
                      icon = Icons.error_outline_rounded;
                    } else if (noticeLevel == 3) {
                      bgColor = context.isDarkMode ? Colors.red.withValues(alpha: 0.1) : Colors.red.shade50;
                      borderColor = context.isDarkMode ? Colors.red.withValues(alpha: 0.3) : Colors.red.shade300;
                      iconColor = context.isDarkMode ? Colors.red.shade400 : Colors.red;
                      title = 'Given Third Notice / Closure';
                      desc = 'Third official notice (Closure) was issued due to continued non-compliance.';
                      icon = Icons.block;
                    } else if (noticeLevel == 4) {
                      bgColor = context.isDarkMode ? Colors.grey.shade900 : Colors.grey.shade200;
                      borderColor = context.isDarkMode ? Colors.grey.shade700 : Colors.grey.shade400;
                      iconColor = context.isDarkMode ? Colors.grey.shade300 : Colors.grey.shade800;
                      title = 'Blacklisted / Closed';
                      desc = 'Establishment has been blacklisted or officially closed.';
                      icon = Icons.lock_outline_rounded;
                    } else {
                      bgColor = context.isDarkMode ? Colors.orange.withValues(alpha: 0.1) : Colors.orange.shade50;
                      borderColor = context.isDarkMode ? Colors.orange.withValues(alpha: 0.3) : Colors.orange.shade300;
                      iconColor = Colors.orange;
                      title = 'Given First Notice';
                      desc = 'First official compliance notice was issued to this establishment.';
                      icon = Icons.warning_amber_rounded;
                    }
                    
                    return Column(
                      children: [
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: bgColor,
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(color: borderColor),
                          ),
                          child: Row(
                            children: [
                              Icon(icon, color: iconColor, size: 24),
                              SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      title,
                                      style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: iconColor),
                                    ),
                                    Text(
                                      desc,
                                      style: TextStyle(fontSize: 11, color: context.isDarkMode ? Colors.grey[300] : Colors.black87),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                        SizedBox(height: 16),
                      ],
                    );
                  }),

                  // Remarks
                  Text(
                    'Remarks',
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                      color: context.adaptiveTextDark,
                    ),
                  ),
                  SizedBox(height: 8),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: Colors.grey[50],
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.grey.shade200),
                    ),
                    child: Text(
                      resolvedTask.remarks ?? 'No remarks provided.',
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.grey[700],
                        height: 1.5,
                      ),
                    ),
                  ),
                ],
              ),
            ),

            SizedBox(height: 20),

            // ── Evidence Section ───────────────────────────────────────────
            _SectionHeader(title: 'Evidence'),
            SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: context.adaptiveSurface,
                borderRadius: BorderRadius.circular(20),
                border: context.isDarkMode ? Border.all(color: Colors.grey.shade700, width: 1) : null,
                boxShadow: [
                  BoxShadow(
                    blurRadius: 10,
                    color: Colors.black.withValues(alpha: 0.08),
                    offset: Offset(0, 4),
                  ),
                ],
              ),
              child: resolvedTask.photoPaths.isNotEmpty
                  ? SizedBox(
                      height: 180,
                      child: ListView.separated(
                        scrollDirection: Axis.horizontal,
                        itemCount: resolvedTask.photoPaths.length,
                        separatorBuilder: (_, _) => SizedBox(width: 8),
                        itemBuilder: (ctx, i) {
                          final absoluteUrl = InspectionService.mediaAbsoluteUrl(resolvedTask.photoPaths[i]);
                          if (absoluteUrl == null) return const SizedBox();
                          return ClipRRect(
                            borderRadius: BorderRadius.circular(10),
                            child: Image.network(
                              absoluteUrl,
                              height: 180,
                              width: 140,
                              fit: BoxFit.cover,
                              errorBuilder: (_, _, _) => Container(
                                height: 180,
                                width: 140,
                                color: Colors.grey[200],
                                child: Icon(Icons.broken_image_outlined, color: Colors.grey),
                              ),
                            ),
                          );
                        },
                      ),
                    )
                  : Center(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        child: Column(
                          children: [
                            Icon(
                              Icons.photo_library_outlined,
                              size: 40,
                              color: Colors.grey[300],
                            ),
                            SizedBox(height: 8),
                            Text(
                              'No evidence photos.',
                              style: TextStyle(
                                color: Colors.grey[400],
                                fontSize: 13,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
            ),

            SizedBox(height: 32),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── Detail Row ───────────────────────────────────────────────────────────────
class _DetailRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  const _DetailRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 16, color: Colors.grey),
        SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: TextStyle(
                  color: Colors.grey,
                  fontSize: 11,
                  fontWeight: FontWeight.w500,
                ),
              ),
              SizedBox(height: 2),
              Text(
                value,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: context.adaptiveTextDark,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// ─── Section Header ───────────────────────────────────────────────────────────
class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.bold,
        color: context.adaptiveTextDark,
      ),
    );
  }
}
