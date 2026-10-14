import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:revela_mobile/pages/notice_document_style.dart';

void main() {
  for (final brightness in Brightness.values) {
    testWidgets('preview body is white and legible in $brightness mode', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(brightness: brightness),
          home: Scaffold(
            body: NoticeDocumentStyle.previewBody('Synthetic notice body'),
          ),
        ),
      );

      final bodyContainer = tester.widget<Container>(
        find
            .ancestor(
              of: find.text('Synthetic notice body'),
              matching: find.byType(Container),
            )
            .first,
      );
      final decoration = bodyContainer.decoration! as BoxDecoration;
      final bodyText = tester.widget<Text>(find.text('Synthetic notice body'));

      expect(decoration.color, Colors.white);
      expect(bodyText.style?.color, NoticeDocumentStyle.bodyTextColor);
      expect(bodyText.data, 'Synthetic notice body');
    });
  }

  test('PDF body uses white fill and serializes notice structure', () async {
    final document = pw.Document(compress: false);
    document.addPage(
      pw.Page(
        pageFormat: PdfPageFormat.a4,
        build: (_) => pw.Column(
          children: [
            pw.Text('Synthetic Official Notice'),
            NoticeDocumentStyle.pdfBody('Synthetic notice body'),
            pw.Text('Synthetic Signatory'),
          ],
        ),
      ),
    );

    final bytes = await document.save();
    final pdfContent = latin1.decode(bytes);

    expect(pdfContent, startsWith('%PDF-'));
    expect(pdfContent, contains('1 1 1 rg'));
    expect(pdfContent, contains('[(Synthetic)]TJ'));
    expect(pdfContent, contains('[(Official)]TJ'));
    expect(pdfContent, contains('[(Notice)]TJ'));
    expect(pdfContent, contains('[(notice)]TJ'));
    expect(pdfContent, contains('[(body)]TJ'));
    expect(pdfContent, contains('[(Signatory)]TJ'));
    expect(pdfContent, isNot(contains('0.8 0.8 0.8 rg')));
  });
}
