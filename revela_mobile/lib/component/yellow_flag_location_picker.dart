import 'package:flutter/material.dart';

import '../service/yellow_flag_candidates.dart';
import '../theme/app_theme.dart';

class YellowFlagLocationPicker extends StatelessWidget {
  const YellowFlagLocationPicker({
    super.key,
    required this.candidates,
    required this.onSelected,
  });

  final List<YellowFlagCandidate> candidates;
  final ValueChanged<YellowFlagCandidate> onSelected;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Select Yellow Flag Location',
              style: TextStyle(
                color: context.adaptiveTextDark,
                fontSize: 18,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<YellowFlagCandidate>(
              initialValue: candidates.isEmpty ? null : candidates.first,
              isExpanded: true,
              isDense: false,
              itemHeight: 80,
              decoration: const InputDecoration(
                labelText: 'Yellow Flag location',
                prefixIcon: Icon(
                  Icons.location_on_rounded,
                  color: Color(0xFFB77900),
                ),
                border: OutlineInputBorder(),
              ),
              items: candidates.map((candidate) {
                return DropdownMenuItem<YellowFlagCandidate>(
                  value: candidate,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${candidate.displayName} · ${candidate.typeLabel}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        candidate.locationDetail,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: context.adaptiveTextMid,
                        ),
                      ),
                    ],
                  ),
                );
              }).toList(),
              onChanged: (candidate) {
                if (candidate != null) onSelected(candidate);
              },
            ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Cancel'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
