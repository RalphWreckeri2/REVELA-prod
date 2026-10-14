import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

class NoticeDocumentStyle {
  static const Color paperBackground = Colors.white;
  static const Color bodyTextColor = Color(0xFF1A1A1A);

  static Widget previewBody(String text) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: paperBackground,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 10,
          color: bodyTextColor,
          height: 1.35,
        ),
        textAlign: TextAlign.justify,
      ),
    );
  }

  static pw.Widget pdfBody(String text) {
    return pw.Container(
      padding: const pw.EdgeInsets.all(8),
      decoration: pw.BoxDecoration(
        color: PdfColors.white,
        borderRadius: pw.BorderRadius.circular(6),
      ),
      child: pw.Text(
        text,
        textAlign: pw.TextAlign.justify,
        style: const pw.TextStyle(fontSize: 10),
      ),
    );
  }
}
