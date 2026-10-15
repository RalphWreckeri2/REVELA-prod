import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

enum LegalPolicyDocument {
  terms('Terms & Conditions', 'assets/legal/terms.md'),
  privacy('Privacy Policy', 'assets/legal/privacy.md'),
  cookies('Cookie & Storage Policy', 'assets/legal/cookies.md');

  const LegalPolicyDocument(this.title, this.assetPath);

  final String title;
  final String assetPath;
}

class LegalPolicyScreen extends StatefulWidget {
  const LegalPolicyScreen({required this.document, super.key});

  final LegalPolicyDocument document;

  @override
  State<LegalPolicyScreen> createState() => _LegalPolicyScreenState();
}

class _LegalPolicyScreenState extends State<LegalPolicyScreen> {
  late final Future<String> _policyContent;

  @override
  void initState() {
    super.initState();
    _policyContent = rootBundle.loadString(widget.document.assetPath);
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(widget.document.title)),
      body: FutureBuilder<String>(
        future: _policyContent,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text('Unable to load this policy. Please try again.'),
              ),
            );
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }

          return SelectionArea(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
              children: _buildMarkdown(context, snapshot.data!, colors),
            ),
          );
        },
      ),
    );
  }

  List<Widget> _buildMarkdown(
    BuildContext context,
    String source,
    ColorScheme colors,
  ) {
    final lines = source.split('\n');
    final widgets = <Widget>[];
    var index = 0;

    while (index < lines.length) {
      final line = lines[index].trimRight();
      if (line.trim().isEmpty) {
        index++;
        continue;
      }

      if (line.startsWith('|')) {
        final rows = <List<String>>[];
        while (index < lines.length &&
            lines[index].trimLeft().startsWith('|')) {
          final row = lines[index].trim().split('|');
          row.removeAt(0);
          if (row.isNotEmpty) row.removeLast();
          if (!row.every(
            (cell) => RegExp(r'^:?-{3,}:?$').hasMatch(cell.trim()),
          )) {
            rows.add(row.map((cell) => cell.trim()).toList());
          }
          index++;
        }
        widgets.add(_buildTable(rows, colors));
        continue;
      }

      if (line.startsWith('### ')) {
        widgets.add(_heading(line.substring(4), colors, level: 3));
      } else if (line.startsWith('## ')) {
        widgets.add(_heading(line.substring(3), colors, level: 2));
      } else if (line.startsWith('# ')) {
        widgets.add(_heading(line.substring(2), colors, level: 1));
      } else if (line.startsWith('> ')) {
        widgets.add(_notice(context, line.substring(2), colors));
      } else if (RegExp(r'^\s*-\s+').hasMatch(line)) {
        final match = RegExp(r'^(\s*)-\s+(.*)$').firstMatch(line)!;
        widgets.add(
          _bullet(
            context,
            match.group(2)!,
            colors,
            indent: (match.group(1)!.length ~/ 2),
          ),
        );
      } else {
        widgets.add(_paragraph(context, line, colors));
      }
      index++;
    }
    return widgets;
  }

  Widget _heading(String text, ColorScheme colors, {required int level}) {
    if (level == 1) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Text(
          text,
          style: TextStyle(
            color: colors.primary,
            fontSize: 25,
            height: 1.2,
            fontWeight: FontWeight.w800,
          ),
        ),
      );
    }
    return Padding(
      padding: EdgeInsets.only(top: level == 2 ? 20 : 12, bottom: 8),
      child: Text(
        text,
        style: TextStyle(
          color: colors.onSurface,
          fontSize: level == 2 ? 18 : 16,
          height: 1.3,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }

  Widget _paragraph(BuildContext context, String text, ColorScheme colors) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text.rich(
        _inlineText(context, text, colors),
        style: TextStyle(
          color: colors.onSurfaceVariant,
          fontSize: 15,
          height: 1.6,
        ),
      ),
    );
  }

  Widget _bullet(
    BuildContext context,
    String text,
    ColorScheme colors, {
    required int indent,
  }) {
    return Padding(
      padding: EdgeInsets.only(left: 12.0 + indent * 14, bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 7, right: 9),
            child: Icon(Icons.circle, size: 6, color: colors.primary),
          ),
          Expanded(
            child: Text.rich(
              _inlineText(context, text, colors),
              style: TextStyle(
                color: colors.onSurfaceVariant,
                fontSize: 15,
                height: 1.55,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _notice(BuildContext context, String text, ColorScheme colors) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.secondaryContainer,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colors.secondary.withValues(alpha: 0.35)),
      ),
      child: Text.rich(
        _inlineText(context, text, colors),
        style: TextStyle(
          color: colors.onSecondaryContainer,
          fontSize: 14,
          height: 1.5,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  Widget _buildTable(List<List<String>> rows, ColorScheme colors) {
    if (rows.isEmpty) return const SizedBox.shrink();
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowColor: WidgetStatePropertyAll(colors.primaryContainer),
        columns: rows.first
            .map(
              (cell) => DataColumn(
                label: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 180),
                  child: Text(
                    cell,
                    style: TextStyle(
                      color: colors.onPrimaryContainer,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            )
            .toList(),
        rows: rows.skip(1).map((row) {
          return DataRow(
            cells: List.generate(
              rows.first.length,
              (column) => DataCell(
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 220),
                  child: Text(
                    column < row.length ? row[column] : '',
                    style: TextStyle(
                      color: colors.onSurfaceVariant,
                      height: 1.4,
                    ),
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  TextSpan _inlineText(BuildContext context, String text, ColorScheme colors) {
    final spans = <InlineSpan>[];
    final pattern = RegExp(r'\*\*(.+?)\*\*|`([^`]+)`');
    var cursor = 0;
    for (final match in pattern.allMatches(text)) {
      if (match.start > cursor) {
        spans.add(TextSpan(text: text.substring(cursor, match.start)));
      }
      if (match.group(1) != null) {
        spans.add(
          TextSpan(
            text: match.group(1),
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        );
      } else {
        spans.add(
          TextSpan(
            text: match.group(2),
            style: TextStyle(
              fontFamily: 'monospace',
              color: colors.primary,
              backgroundColor: colors.surfaceContainerHighest,
            ),
          ),
        );
      }
      cursor = match.end;
    }
    if (cursor < text.length) spans.add(TextSpan(text: text.substring(cursor)));
    return TextSpan(children: spans);
  }
}

Future<void> showLegalPolicy(
  BuildContext context,
  LegalPolicyDocument document,
) {
  return Navigator.of(context).push<void>(
    MaterialPageRoute<void>(
      builder: (_) => LegalPolicyScreen(document: document),
    ),
  );
}
