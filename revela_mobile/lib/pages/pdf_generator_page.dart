import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';
import 'package:google_fonts/google_fonts.dart';
import '../service/inspection_service.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:image_picker/image_picker.dart';
import '../theme/app_theme.dart';
import '../widgets/custom_app_bar.dart';

class PdfGeneratorPage extends StatefulWidget {
  final InspectionTask? initialTask;
  const PdfGeneratorPage({super.key, this.initialTask});

  @override
  State<PdfGeneratorPage> createState() => _PdfGeneratorPageState();
}

class _PdfGeneratorPageState extends State<PdfGeneratorPage> {
  final InspectionService _inspectionService = InspectionService();
  List<InspectionTask> _allTasks = [];
  InspectionTask? _selectedTask;
  bool _isLoading = true;
  bool _showEditForm = false;

  // Custom Logos & Signature
  String? _signatureBase64;
  String? _leftLogoBase64;
  String? _rightLogoBase64;

  // Selected Edit Category Tab (0: Header & Logos, 1: Content & Signature, 2: Footer)
  int _selectedEditCategory = 0;

  // ── Header Controllers ──
  final TextEditingController _headerLine1Controller =
      TextEditingController(text: 'Republika ng Pilipinas');
  final TextEditingController _headerLine2Controller =
      TextEditingController(text: 'Lalawigan ng Batangas');
  final TextEditingController _headerLine3Controller =
      TextEditingController(text: 'Bayan ng Mataasnakahoy');
  final TextEditingController _officeTitleController =
      TextEditingController(text: 'TANGGAPAN NG PUNUMBAYAN');
  final TextEditingController _contactController =
      TextEditingController(text: 'Telepono #: 461-2374');
  final TextEditingController _emailController =
      TextEditingController(text: 'Email: licensingoffice2374@yahoo.com');
  final TextEditingController _sectionTitleController = TextEditingController(
    text: 'SEKSYON NG PANGKALAKALANG KAPAHINTULUTAN AT LISENSYA',
  );

  // ── Content Controllers ──
  final TextEditingController _ownerNameController = TextEditingController();
  final TextEditingController _addressController = TextEditingController();
  final TextEditingController _natureOfBusinessController =
      TextEditingController();
  final TextEditingController _customBodyController = TextEditingController();
  final TextEditingController _closingGreetingController =
      TextEditingController(text: 'Lubos na gumagalang,');
  final TextEditingController _signatoryNameController = TextEditingController(
    text: 'MIAN S. CASTILLO',
  );
  final TextEditingController _signatoryPositionController =
      TextEditingController(text: 'Licensing Officer II');

  // ── Footer Controllers ──
  final TextEditingController _footerTaglineController = TextEditingController(
    text: 'Health | Opportunity | Peace & Order | Education & Economy',
  );
  final TextEditingController _footerMottoController = TextEditingController(
    text: 'L O V E M A T A A S N A K A H O Y',
  );

  @override
  void dispose() {
    _headerLine1Controller.dispose();
    _headerLine2Controller.dispose();
    _headerLine3Controller.dispose();
    _officeTitleController.dispose();
    _contactController.dispose();
    _emailController.dispose();
    _sectionTitleController.dispose();

    _ownerNameController.dispose();
    _addressController.dispose();
    _natureOfBusinessController.dispose();
    _customBodyController.dispose();
    _closingGreetingController.dispose();
    _signatoryNameController.dispose();
    _signatoryPositionController.dispose();

    _footerTaglineController.dispose();
    _footerMottoController.dispose();
    super.dispose();
  }

  String get _formattedDate {
    final now = DateTime.now();
    const months = [
      'Enero',
      'Pebrero',
      'Marso',
      'Abril',
      'Mayo',
      'Hunyo',
      'Hulyo',
      'Agosto',
      'Setyembre',
      'Oktubre',
      'Nobyembre',
      'Disyembre',
    ];
    return '${months[now.month - 1]} ${now.day}, ${now.year}';
  }

  String get _autoNoticeText {
    final lvl = _selectedTask?.currentNoticeLevel ?? 0;
    final biz = _natureOfBusinessController.text.trim();
    final bizText = biz.isEmpty ? "(NATURE OF BUSINESS)" : biz;

    if (lvl == 1) {
      return "Muli po naming ipinababatid sa inyo na ayon po sa aming talaan ng aming tanggapan, na ang inyo pong $bizText matagal ng hindi nakukuha ng kaukulang permiso (BUSINESS AND MAYOR'S PERMIT).\n\nSa kadahilanang pong ito, kayo ay malugod naming inaanyayahang makipag-ugnayan sa aming tanggapan sa loob ng limang (5) araw pagkatanggap ninyo ng liham na ito.";
    } else if (lvl >= 2) {
      return "Magandang Araw po!\n\nNais po naming tawagin ang inyong pansin sa hindi ninyo pagtalima at pagpansin sa kabila ng aming abiso hinggil sa hindi ninyo pagtubos ng karampatang Permiso o Lisensya para sa inyong negosyo. Ito po ay labag sa ating ORDINANSA BLG. 27-S-96.\n\nHinggil po dito, kayo po ay aming inaanyayahang magsadya sa aming tanggapan sa loob ng tatlong (3) araw pagkatanggap ninyo ng liham na ito.\n\nAng hindi po ninyo pagpansin sa aming abiso ay magiging basehan namin upang ipatigil ang patuloy ninyong illegal na pagpapatakbo ng negosyo.";
    } else {
      return "Ayon po sa talaan ng aming tanggapan, ang inyo pong $bizText hindi pa nakukuha ng kaukulang permiso (BUSINESS AND MAYOR'S PERMIT).\n\nSa kadahilanang pong ito, kayo ay malugod naming inaanyayahang makipag-ugnayan sa aming tanggapan sa loob ng tatlong (3) araw pagkatanggap ninyo ng liham na ito.";
    }
  }

  String get _effectiveCertificationText {
    if (_customBodyController.text.trim().isNotEmpty) {
      return _customBodyController.text.trim();
    }
    return _autoNoticeText;
  }

  @override
  void initState() {
    super.initState();
    _loadTasks();
    _loadCustomSettings();
  }

  Future<void> _loadCustomSettings() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _signatureBase64 = prefs.getString('saved_signature_base64');
      _leftLogoBase64 = prefs.getString('saved_left_logo_base64');
      _rightLogoBase64 = prefs.getString('saved_right_logo_base64');

      if (prefs.containsKey('saved_header_line1')) {
        _headerLine1Controller.text = prefs.getString('saved_header_line1')!;
      }
      if (prefs.containsKey('saved_header_line2')) {
        _headerLine2Controller.text = prefs.getString('saved_header_line2')!;
      }
      if (prefs.containsKey('saved_header_line3')) {
        _headerLine3Controller.text = prefs.getString('saved_header_line3')!;
      }
      if (prefs.containsKey('saved_office_title')) {
        _officeTitleController.text = prefs.getString('saved_office_title')!;
      }
      if (prefs.containsKey('saved_contact')) {
        _contactController.text = prefs.getString('saved_contact')!;
      }
      if (prefs.containsKey('saved_email')) {
        _emailController.text = prefs.getString('saved_email')!;
      }
      if (prefs.containsKey('saved_section_title')) {
        _sectionTitleController.text = prefs.getString('saved_section_title')!;
      }
      if (prefs.containsKey('saved_closing_greeting')) {
        _closingGreetingController.text = prefs.getString('saved_closing_greeting')!;
      }
      if (prefs.containsKey('saved_signatory_name')) {
        _signatoryNameController.text = prefs.getString('saved_signatory_name')!;
      }
      if (prefs.containsKey('saved_signatory_position')) {
        _signatoryPositionController.text = prefs.getString('saved_signatory_position')!;
      }
      if (prefs.containsKey('saved_footer_tagline')) {
        _footerTaglineController.text = prefs.getString('saved_footer_tagline')!;
      }
      if (prefs.containsKey('saved_footer_motto')) {
        _footerMottoController.text = prefs.getString('saved_footer_motto')!;
      }
    });
  }

  Future<void> _saveCustomSettings() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('saved_header_line1', _headerLine1Controller.text);
    await prefs.setString('saved_header_line2', _headerLine2Controller.text);
    await prefs.setString('saved_header_line3', _headerLine3Controller.text);
    await prefs.setString('saved_office_title', _officeTitleController.text);
    await prefs.setString('saved_contact', _contactController.text);
    await prefs.setString('saved_email', _emailController.text);
    await prefs.setString('saved_section_title', _sectionTitleController.text);
    await prefs.setString('saved_closing_greeting', _closingGreetingController.text);
    await prefs.setString('saved_signatory_name', _signatoryNameController.text);
    await prefs.setString('saved_signatory_position', _signatoryPositionController.text);
    await prefs.setString('saved_footer_tagline', _footerTaglineController.text);
    await prefs.setString('saved_footer_motto', _footerMottoController.text);
  }

  Future<void> _resetToDefaults() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('saved_left_logo_base64');
    await prefs.remove('saved_right_logo_base64');
    await prefs.remove('saved_header_line1');
    await prefs.remove('saved_header_line2');
    await prefs.remove('saved_header_line3');
    await prefs.remove('saved_office_title');
    await prefs.remove('saved_contact');
    await prefs.remove('saved_email');
    await prefs.remove('saved_section_title');
    await prefs.remove('saved_closing_greeting');
    await prefs.remove('saved_signatory_name');
    await prefs.remove('saved_signatory_position');
    await prefs.remove('saved_footer_tagline');
    await prefs.remove('saved_footer_motto');

    setState(() {
      _leftLogoBase64 = null;
      _rightLogoBase64 = null;
      _headerLine1Controller.text = 'Republika ng Pilipinas';
      _headerLine2Controller.text = 'Lalawigan ng Batangas';
      _headerLine3Controller.text = 'Bayan ng Mataasnakahoy';
      _officeTitleController.text = 'TANGGAPAN NG PUNUMBAYAN';
      _contactController.text = 'Telepono #: 461-2374';
      _emailController.text = 'Email: licensingoffice2374@yahoo.com';
      _sectionTitleController.text = 'SEKSYON NG PANGKALAKALANG KAPAHINTULUTAN AT LISENSYA';
      _customBodyController.clear();
      _closingGreetingController.text = 'Lubos na gumagalang,';
      _signatoryNameController.text = 'MIAN S. CASTILLO';
      _signatoryPositionController.text = 'Licensing Officer II';
      _footerTaglineController.text = 'Health | Opportunity | Peace & Order | Education & Economy';
      _footerMottoController.text = 'L O V E M A T A A S N A K A H O Y';
    });

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Document layout reset to default municipality template.'),
          backgroundColor: AppColors.darkGreen,
        ),
      );
    }
  }

  Future<void> _pickSignature() async {
    final picker = ImagePicker();
    final pickedFile = await picker.pickImage(source: ImageSource.gallery, maxWidth: 800);
    if (pickedFile != null) {
      final bytes = await pickedFile.readAsBytes();
      final base64String = base64Encode(bytes);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('saved_signature_base64', base64String);
      setState(() => _signatureBase64 = base64String);
    }
  }

  Future<void> _removeSignature() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('saved_signature_base64');
    setState(() => _signatureBase64 = null);
  }

  Future<void> _pickLeftLogo() async {
    final picker = ImagePicker();
    final pickedFile = await picker.pickImage(source: ImageSource.gallery, maxWidth: 800);
    if (pickedFile != null) {
      final bytes = await pickedFile.readAsBytes();
      final base64String = base64Encode(bytes);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('saved_left_logo_base64', base64String);
      setState(() => _leftLogoBase64 = base64String);
    }
  }

  Future<void> _removeLeftLogo() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('saved_left_logo_base64');
    setState(() => _leftLogoBase64 = null);
  }

  Future<void> _pickRightLogo() async {
    final picker = ImagePicker();
    final pickedFile = await picker.pickImage(source: ImageSource.gallery, maxWidth: 800);
    if (pickedFile != null) {
      final bytes = await pickedFile.readAsBytes();
      final base64String = base64Encode(bytes);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('saved_right_logo_base64', base64String);
      setState(() => _rightLogoBase64 = base64String);
    }
  }

  Future<void> _removeRightLogo() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('saved_right_logo_base64');
    setState(() => _rightLogoBase64 = null);
  }

  void _showSearchModal(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) {
        return _SearchModal(
          tasks: _allTasks,
          onSelected: (task) {
            setState(() {
              _selectedTask = task;
              _addressController.text =
                  'Brgy. ${task.barangayName}, Mataasnakahoy Batangas';
            });
          },
        );
      },
    );
  }

  Future<void> _loadTasks() async {
    setState(() => _isLoading = true);
    try {
      final active = await _inspectionService.getMyTasks();
      final history = await _inspectionService.getMyReportHistory();
      final combined = [...active, ...history];

      final uniqueTasks = <int, InspectionTask>{};
      for (final t in combined) {
        uniqueTasks[t.reportID] = t;
      }
      final deduped = uniqueTasks.values.toList();

      if (mounted) {
        setState(() {
          _allTasks = deduped;
          _selectedTask =
              widget.initialTask ?? (deduped.isNotEmpty ? deduped.first : null);
          if (_selectedTask != null) {
            _addressController.text =
                'Brgy. ${_selectedTask!.barangayName}, Mataasnakahoy Batangas';
          }
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<Uint8List> _generatePdfDocument(PdfPageFormat format) async {
    final pdf = pw.Document();

    pw.ImageProvider leftImage;
    if (_leftLogoBase64 != null && _leftLogoBase64!.isNotEmpty) {
      leftImage = pw.MemoryImage(base64Decode(_leftLogoBase64!));
    } else {
      final mtkSealBytes = await rootBundle.load('assets/images/seal.png');
      leftImage = pw.MemoryImage(mtkSealBytes.buffer.asUint8List());
    }

    pw.ImageProvider rightImage;
    if (_rightLogoBase64 != null && _rightLogoBase64!.isNotEmpty) {
      rightImage = pw.MemoryImage(base64Decode(_rightLogoBase64!));
    } else {
      final bpSealBytes = await rootBundle.load('assets/images/bagongpilipinas.png');
      rightImage = pw.MemoryImage(bpSealBytes.buffer.asUint8List());
    }

    final footerFont = await PdfGoogleFonts.montserratBold();

    pdf.addPage(
      pw.MultiPage(
        pageFormat: format,
        margin: const pw.EdgeInsets.fromLTRB(18, 18, 18, 72),
        footer: (pw.Context context) {
          return pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.stretch,
            mainAxisSize: pw.MainAxisSize.min,
            children: [
              if (_footerTaglineController.text.trim().isNotEmpty)
                pw.Text(
                  _footerTaglineController.text.trim(),
                  textAlign: pw.TextAlign.center,
                  style: pw.TextStyle(
                    fontSize: 9,
                    fontWeight: pw.FontWeight.bold,
                    color: PdfColors.blue900,
                  ),
                ),
              pw.SizedBox(height: 2),
              if (_footerMottoController.text.trim().isNotEmpty)
                pw.Text(
                  _footerMottoController.text.trim(),
                  textAlign: pw.TextAlign.center,
                  style: pw.TextStyle(
                    font: footerFont,
                    fontSize: 10,
                    fontWeight: pw.FontWeight.bold,
                    color: PdfColors.orange900,
                    letterSpacing: 1.5,
                  ),
                ),
            ],
          );
        },
        build: (pw.Context context) => [
          pw.Container(
            padding: const pw.EdgeInsets.all(18),
            child: pw.Column(
              crossAxisAlignment: pw.CrossAxisAlignment.stretch,
              children: [
                pw.Row(
                  mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: pw.CrossAxisAlignment.center,
                  children: [
                    pw.Container(
                      width: 46,
                      height: 46,
                      child: pw.Image(leftImage, fit: pw.BoxFit.contain),
                    ),
                    pw.Expanded(
                      child: pw.Column(
                        crossAxisAlignment: pw.CrossAxisAlignment.center,
                        children: [
                          if (_headerLine1Controller.text.trim().isNotEmpty)
                            pw.Text(
                              _headerLine1Controller.text.trim(),
                              style: const pw.TextStyle(fontSize: 9),
                            ),
                          if (_headerLine2Controller.text.trim().isNotEmpty)
                            pw.Text(
                              _headerLine2Controller.text.trim(),
                              style: const pw.TextStyle(fontSize: 9),
                            ),
                          if (_headerLine3Controller.text.trim().isNotEmpty)
                            pw.Text(
                              _headerLine3Controller.text.trim(),
                              style: const pw.TextStyle(fontSize: 9),
                            ),
                          if (_officeTitleController.text.trim().isNotEmpty) ...[
                            pw.SizedBox(height: 1),
                            pw.Text(
                              _officeTitleController.text.trim(),
                              style: pw.TextStyle(
                                fontSize: 9,
                                fontWeight: pw.FontWeight.bold,
                              ),
                            ),
                          ],
                          if (_contactController.text.trim().isNotEmpty) ...[
                            pw.SizedBox(height: 1),
                            pw.Text(
                              _contactController.text.trim(),
                              style: const pw.TextStyle(fontSize: 9),
                            ),
                          ],
                          if (_emailController.text.trim().isNotEmpty) ...[
                            pw.SizedBox(height: 1),
                            pw.Text(
                              _emailController.text.trim(),
                              style: const pw.TextStyle(
                                fontSize: 9,
                                color: PdfColors.blue,
                                decoration: pw.TextDecoration.underline,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    pw.Container(
                      width: 46,
                      height: 46,
                      child: pw.Image(rightImage, fit: pw.BoxFit.contain),
                    ),
                  ],
                ),
                pw.SizedBox(height: 14),
                if (_sectionTitleController.text.trim().isNotEmpty)
                  pw.Text(
                    _sectionTitleController.text.trim(),
                    textAlign: pw.TextAlign.center,
                    style: pw.TextStyle(
                      fontSize: 11,
                      fontWeight: pw.FontWeight.bold,
                    ),
                  ),
                pw.SizedBox(height: 14),
                pw.Container(
                  alignment: pw.Alignment.centerRight,
                  child: pw.Text(
                    _formattedDate,
                    style: const pw.TextStyle(fontSize: 10),
                  ),
                ),
                pw.SizedBox(height: 16),
                pw.Align(
                  alignment: pw.Alignment.centerLeft,
                  child: pw.Column(
                    crossAxisAlignment: pw.CrossAxisAlignment.start,
                    children: [
                      pw.Text(
                        'To the Owner/Representative:',
                        style: pw.TextStyle(
                          fontSize: 10,
                          fontWeight: pw.FontWeight.bold,
                        ),
                      ),
                      pw.SizedBox(height: 6),
                      pw.Text(
                        _ownerNameController.text.trim().isEmpty
                            ? '______________________'
                            : _ownerNameController.text.trim(),
                        style: pw.TextStyle(
                          fontSize: 10,
                          fontWeight: pw.FontWeight.bold,
                        ),
                      ),
                      pw.SizedBox(height: 2),
                      pw.Text(
                        _addressController.text.trim().isEmpty
                            ? '______________________'
                            : _addressController.text.trim(),
                        style: const pw.TextStyle(fontSize: 10),
                      ),
                    ],
                  ),
                ),
                pw.SizedBox(height: 12),
                pw.Container(
                  padding: const pw.EdgeInsets.all(8),
                  decoration: pw.BoxDecoration(
                    color: PdfColors.grey200,
                    borderRadius: pw.BorderRadius.circular(6),
                  ),
                  child: pw.Text(
                    _effectiveCertificationText,
                    textAlign: pw.TextAlign.justify,
                    style: const pw.TextStyle(fontSize: 10),
                  ),
                ),
                pw.SizedBox(height: 12),
                pw.Text(
                  'Maraming salamat po.',
                  style: const pw.TextStyle(fontSize: 10),
                ),
                pw.SizedBox(height: 12),
                pw.Align(
                  alignment: pw.Alignment.centerRight,
                  child: pw.Column(
                    crossAxisAlignment: pw.CrossAxisAlignment.center,
                    children: [
                      pw.Text(
                        _closingGreetingController.text.trim().isEmpty
                            ? 'Lubos na gumagalang,'
                            : _closingGreetingController.text.trim(),
                        style: const pw.TextStyle(fontSize: 10),
                      ),
                      pw.SizedBox(height: 24),
                      pw.Stack(
                        alignment: pw.Alignment.bottomCenter,
                        children: [
                          if (_signatureBase64 != null)
                            pw.Positioned(
                              bottom: 12,
                              child: pw.Container(
                                height: 60,
                                child: pw.Image(
                                  pw.MemoryImage(
                                    base64Decode(_signatureBase64!),
                                  ),
                                  fit: pw.BoxFit.contain,
                                ),
                              ),
                            ),
                          pw.Column(
                            crossAxisAlignment: pw.CrossAxisAlignment.center,
                            children: [
                              pw.Text(
                                _signatoryNameController.text.trim().isEmpty
                                    ? '______________________'
                                    : _signatoryNameController.text.trim(),
                                style: pw.TextStyle(
                                  fontSize: 10,
                                  fontWeight: pw.FontWeight.bold,
                                ),
                              ),
                              pw.SizedBox(height: 2),
                              pw.Text(
                                _signatoryPositionController.text.trim().isEmpty
                                    ? '______________________'
                                    : _signatoryPositionController.text.trim(),
                                style: const pw.TextStyle(fontSize: 10),
                              ),
                            ],
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
    );

    return pdf.save();
  }

  void _handlePrint() async {
    if (_selectedTask == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please select an establishment first.'),
          backgroundColor: Colors.redAccent,
        ),
      );
      return;
    }
    await Printing.layoutPdf(
      onLayout: (PdfPageFormat format) async => _generatePdfDocument(format),
      name: 'BPLO_Notice_${_selectedTask!.reportID}.pdf',
    );
  }

  void _handleExportPdf() async {
    if (_selectedTask == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please select an establishment first.'),
          backgroundColor: Colors.redAccent,
        ),
      );
      return;
    }
    try {
      final bytes = await _generatePdfDocument(PdfPageFormat.a4);
      await Printing.sharePdf(
        bytes: bytes,
        filename: 'BPLO_Notice_${_selectedTask!.reportID}.pdf',
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Error exporting PDF: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: const CustomAppBar(
        title: 'Notice Generator',
        icon: Icons.picture_as_pdf_rounded,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _allTasks.isEmpty
          ? const Center(
              child: Text(
                'No inspection records available to generate notice.',
              ),
            )
          : SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 240),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // ── Selection Controls Card ──
                  Card(
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16),
                    ),
                    elevation: 2,
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Establishment Selection',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 16,
                              color: context.adaptiveTextDark,
                            ),
                          ),
                          const SizedBox(height: 12),
                          InkWell(
                            onTap: () => _showSearchModal(context),
                            borderRadius: BorderRadius.circular(4),
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: 'Select Establishment *',
                                border: OutlineInputBorder(),
                                prefixIcon: Icon(Icons.search),
                                suffixIcon: Icon(Icons.arrow_drop_down),
                              ),
                              child: Text(
                                _selectedTask != null
                                    ? '${_selectedTask!.detectedName} (${_selectedTask!.barangayName})'
                                    : 'Tap to search...',
                                style: TextStyle(
                                  color: _selectedTask != null
                                      ? context.adaptiveTextDark
                                      : context.adaptiveTextMid,
                                  fontSize: 16,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ),
                          if (_selectedTask != null) ...[
                            const SizedBox(height: 12),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 12,
                                vertical: 6,
                              ),
                              decoration: BoxDecoration(
                                color: _selectedTask!.currentNoticeLevel == 0
                                    ? Colors.blue.withValues(alpha: 0.1)
                                    : _selectedTask!.currentNoticeLevel == 1
                                    ? Colors.orange.withValues(alpha: 0.1)
                                    : Colors.red.withValues(alpha: 0.1),
                                borderRadius: BorderRadius.circular(16),
                                border: Border.all(
                                  color: _selectedTask!.currentNoticeLevel == 0
                                      ? Colors.blue
                                      : _selectedTask!.currentNoticeLevel == 1
                                      ? Colors.orange
                                      : Colors.red,
                                ),
                              ),
                              child: Text(
                                _selectedTask!.currentNoticeLevel == 0
                                    ? 'Generating: FIRST NOTICE'
                                    : _selectedTask!.currentNoticeLevel == 1
                                    ? 'Generating: SECOND NOTICE'
                                    : 'Generating: FINAL NOTICE (CLOSURE ORDER)',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: _selectedTask!.currentNoticeLevel == 0
                                      ? Colors.blue
                                      : _selectedTask!.currentNoticeLevel == 1
                                      ? Colors.orange
                                      : Colors.red,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),

                  // ── Comprehensive Editable PDF Settings Card (Header, Content, Footer) ──
                  Card(
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16),
                    ),
                    elevation: 2,
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                'Customize Document Content',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 16,
                                  color: context.adaptiveTextDark,
                                ),
                              ),
                              IconButton(
                                icon: Icon(
                                  _showEditForm
                                      ? Icons.expand_less
                                      : Icons.edit,
                                ),
                                onPressed: () {
                                  setState(
                                    () => _showEditForm = !_showEditForm,
                                  );
                                },
                              ),
                            ],
                          ),
                          if (_showEditForm) ...[
                            const SizedBox(height: 12),
                            // Category Tab Buttons (Header & Logos, Body & Signature, Footer)
                            Row(
                              children: [
                                Expanded(
                                  child: ChoiceChip(
                                    label: const Text('Header & Logos'),
                                    selected: _selectedEditCategory == 0,
                                    onSelected: (val) {
                                      if (val) setState(() => _selectedEditCategory = 0);
                                    },
                                  ),
                                ),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: ChoiceChip(
                                    label: const Text('Body & Sign'),
                                    selected: _selectedEditCategory == 1,
                                    onSelected: (val) {
                                      if (val) setState(() => _selectedEditCategory = 1);
                                    },
                                  ),
                                ),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: ChoiceChip(
                                    label: const Text('Footer'),
                                    selected: _selectedEditCategory == 2,
                                    onSelected: (val) {
                                      if (val) setState(() => _selectedEditCategory = 2);
                                    },
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 16),

                            // ── CATEGORY 0: HEADER & LOGOS ──
                            if (_selectedEditCategory == 0) ...[
                              Text(
                                'Header Logos',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: context.adaptiveTextDark,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      children: [
                                        Text('Left Logo (Seal 1)', style: TextStyle(fontSize: 12, color: context.adaptiveTextMid)),
                                        const SizedBox(height: 6),
                                        Container(
                                          height: 50,
                                          width: 50,
                                          decoration: BoxDecoration(
                                            border: Border.all(color: context.adaptiveBorder),
                                            borderRadius: BorderRadius.circular(8),
                                          ),
                                          child: _leftLogoBase64 != null
                                              ? Image.memory(base64Decode(_leftLogoBase64!), fit: BoxFit.contain)
                                              : Image.asset('assets/images/seal.png', fit: BoxFit.contain),
                                        ),
                                        const SizedBox(height: 4),
                                        Row(
                                          mainAxisAlignment: MainAxisAlignment.center,
                                          children: [
                                            IconButton(
                                              icon: const Icon(Icons.upload, size: 18),
                                              onPressed: _pickLeftLogo,
                                              tooltip: 'Upload Left Logo',
                                            ),
                                            if (_leftLogoBase64 != null)
                                              IconButton(
                                                icon: const Icon(Icons.delete, size: 18, color: Colors.red),
                                                onPressed: _removeLeftLogo,
                                                tooltip: 'Reset Left Logo',
                                              ),
                                          ],
                                        ),
                                      ],
                                    ),
                                  ),
                                  Expanded(
                                    child: Column(
                                      children: [
                                        Text('Right Logo (Seal 2)', style: TextStyle(fontSize: 12, color: context.adaptiveTextMid)),
                                        const SizedBox(height: 6),
                                        Container(
                                          height: 50,
                                          width: 50,
                                          decoration: BoxDecoration(
                                            border: Border.all(color: context.adaptiveBorder),
                                            borderRadius: BorderRadius.circular(8),
                                          ),
                                          child: _rightLogoBase64 != null
                                              ? Image.memory(base64Decode(_rightLogoBase64!), fit: BoxFit.contain)
                                              : Image.asset('assets/images/bagongpilipinas.png', fit: BoxFit.contain),
                                        ),
                                        const SizedBox(height: 4),
                                        Row(
                                          mainAxisAlignment: MainAxisAlignment.center,
                                          children: [
                                            IconButton(
                                              icon: const Icon(Icons.upload, size: 18),
                                              onPressed: _pickRightLogo,
                                              tooltip: 'Upload Right Logo',
                                            ),
                                            if (_rightLogoBase64 != null)
                                              IconButton(
                                                icon: const Icon(Icons.delete, size: 18, color: Colors.red),
                                                onPressed: _removeRightLogo,
                                                tooltip: 'Reset Right Logo',
                                              ),
                                          ],
                                        ),
                                      ],
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 14),
                              TextField(
                                controller: _headerLine1Controller,
                                decoration: const InputDecoration(labelText: 'Header Line 1 (Country/Government)'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 10),
                              TextField(
                                controller: _headerLine2Controller,
                                decoration: const InputDecoration(labelText: 'Header Line 2 (Province)'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 10),
                              TextField(
                                controller: _headerLine3Controller,
                                decoration: const InputDecoration(labelText: 'Header Line 3 (Municipality/City)'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 10),
                              TextField(
                                controller: _officeTitleController,
                                decoration: const InputDecoration(labelText: 'Office Title'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 10),
                              TextField(
                                controller: _contactController,
                                decoration: const InputDecoration(labelText: 'Contact Telepono / Phone'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 10),
                              TextField(
                                controller: _emailController,
                                decoration: const InputDecoration(labelText: 'Office Email Address'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 10),
                              TextField(
                                controller: _sectionTitleController,
                                decoration: const InputDecoration(labelText: 'Document / Section Title Banner'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                            ],

                            // ── CATEGORY 1: BODY & SIGNATURE ──
                            if (_selectedEditCategory == 1) ...[
                              TextField(
                                controller: _ownerNameController,
                                decoration: const InputDecoration(
                                  labelText: 'Owner/Representative Name',
                                  hintText: 'Leave blank for underline',
                                ),
                                onChanged: (_) => setState(() {}),
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _addressController,
                                decoration: const InputDecoration(labelText: 'Address'),
                                onChanged: (_) => setState(() {}),
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _natureOfBusinessController,
                                decoration: const InputDecoration(
                                  labelText: 'Nature of Business',
                                  hintText: 'e.g. Sari-Sari Store, Hardware',
                                ),
                                onChanged: (_) => setState(() {}),
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _customBodyController,
                                maxLines: 3,
                                minLines: 2,
                                decoration: const InputDecoration(
                                  labelText: 'Custom Body Notice Message (Optional)',
                                  hintText: 'Leave blank to use automatic Notice template text based on establishment level.',
                                ),
                                onChanged: (_) => setState(() {}),
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _closingGreetingController,
                                decoration: const InputDecoration(labelText: 'Closing Greeting'),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _signatoryNameController,
                                decoration: const InputDecoration(
                                  labelText: 'Signatory Name',
                                ),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _signatoryPositionController,
                                decoration: const InputDecoration(
                                  labelText: 'Signatory Position',
                                ),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 16),
                              Text(
                                'E-Signature',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: context.adaptiveTextDark,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '(Upload an image with transparent background to overlay on signatory line)',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: context.adaptiveTextMid,
                                ),
                              ),
                              const SizedBox(height: 8),
                              _signatureBase64 != null
                                  ? Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Container(
                                          height: 60,
                                          padding: const EdgeInsets.all(4),
                                          decoration: BoxDecoration(
                                            border: Border.all(
                                              color: context.adaptiveBorder,
                                            ),
                                            borderRadius: BorderRadius.circular(
                                              8,
                                            ),
                                          ),
                                          child: Image.memory(
                                            base64Decode(_signatureBase64!),
                                          ),
                                        ),
                                        TextButton.icon(
                                          onPressed: _removeSignature,
                                          icon: const Icon(
                                            Icons.delete,
                                            color: Colors.red,
                                          ),
                                          label: const Text(
                                            'Remove Signature',
                                            style: TextStyle(color: Colors.red),
                                          ),
                                        ),
                                      ],
                                    )
                                  : ElevatedButton.icon(
                                      onPressed: _pickSignature,
                                      icon: const Icon(Icons.upload),
                                      label: const Text('Upload E-Signature'),
                                    ),
                            ],

                            // ── CATEGORY 2: FOOTER ──
                            if (_selectedEditCategory == 2) ...[
                              TextField(
                                controller: _footerTaglineController,
                                decoration: const InputDecoration(
                                  labelText: 'Footer Tagline Line 1',
                                  hintText: 'e.g. Health | Opportunity | Peace & Order...',
                                ),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _footerMottoController,
                                decoration: const InputDecoration(
                                  labelText: 'Footer Motto Line 2',
                                  hintText: 'e.g. L O V E M A T A A S N A K A H O Y',
                                ),
                                onChanged: (_) { _saveCustomSettings(); setState(() {}); },
                              ),
                              const SizedBox(height: 20),
                              SizedBox(
                                width: double.infinity,
                                child: OutlinedButton.icon(
                                  onPressed: _resetToDefaults,
                                  icon: const Icon(Icons.restore, color: Colors.orange),
                                  label: const Text('Reset All Settings to Default Template'),
                                  style: OutlinedButton.styleFrom(
                                    foregroundColor: Colors.orange,
                                    side: const BorderSide(color: Colors.orange),
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ],
                      ),
                    ),
                  ),

                  const SizedBox(height: 20),

                  // ── Live Document Preview Paper ──
                  Text(
                    'Live Document Preview',
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                      color: context.adaptiveTextDark,
                    ),
                  ),
                  const SizedBox(height: 10),
                  AspectRatio(
                    aspectRatio: 8.5 / 11,
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: context.adaptiveSurface,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: context.adaptiveBorder,
                          width: 1.5,
                        ),
                        boxShadow: [
                          BoxShadow(
                            color: Colors.black.withValues(alpha: 0.06),
                            blurRadius: 12,
                            offset: const Offset(0, 4),
                          ),
                        ],
                      ),
                      child: SingleChildScrollView(
                        child: Column(
                          children: [
                            // Header Seals & Title
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.center,
                              children: [
                                SizedBox(
                                  width: 42,
                                  height: 42,
                                  child: _leftLogoBase64 != null
                                      ? Image.memory(base64Decode(_leftLogoBase64!), fit: BoxFit.contain)
                                      : Image.asset('assets/images/seal.png', fit: BoxFit.contain),
                                ),
                                Expanded(
                                  child: Column(
                                    children: [
                                      if (_headerLine1Controller.text.trim().isNotEmpty)
                                        Text(
                                          _headerLine1Controller.text.trim(),
                                          textAlign: TextAlign.center,
                                          style: const TextStyle(fontSize: 9, fontWeight: FontWeight.normal),
                                        ),
                                      if (_headerLine2Controller.text.trim().isNotEmpty)
                                        Text(
                                          _headerLine2Controller.text.trim(),
                                          textAlign: TextAlign.center,
                                          style: const TextStyle(fontSize: 9, fontWeight: FontWeight.normal),
                                        ),
                                      if (_headerLine3Controller.text.trim().isNotEmpty)
                                        Text(
                                          _headerLine3Controller.text.trim(),
                                          textAlign: TextAlign.center,
                                          style: const TextStyle(fontSize: 9, fontWeight: FontWeight.normal),
                                        ),
                                      if (_officeTitleController.text.trim().isNotEmpty)
                                        Text(
                                          _officeTitleController.text.trim(),
                                          textAlign: TextAlign.center,
                                          style: const TextStyle(fontSize: 9, fontWeight: FontWeight.bold),
                                        ),
                                      if (_contactController.text.trim().isNotEmpty)
                                        Text(
                                          _contactController.text.trim(),
                                          textAlign: TextAlign.center,
                                          style: const TextStyle(fontSize: 9, fontWeight: FontWeight.normal),
                                        ),
                                      if (_emailController.text.trim().isNotEmpty)
                                        Text(
                                          _emailController.text.trim(),
                                          textAlign: TextAlign.center,
                                          style: const TextStyle(
                                            fontSize: 9,
                                            fontWeight: FontWeight.normal,
                                            color: Colors.blue,
                                            decoration: TextDecoration.underline,
                                          ),
                                        ),
                                    ],
                                  ),
                                ),
                                SizedBox(
                                  width: 42,
                                  height: 42,
                                  child: _rightLogoBase64 != null
                                      ? Image.memory(base64Decode(_rightLogoBase64!), fit: BoxFit.contain)
                                      : Image.asset('assets/images/bagongpilipinas.png', fit: BoxFit.contain),
                                ),
                              ],
                            ),
                            const Divider(height: 20, thickness: 1.2),

                            if (_sectionTitleController.text.trim().isNotEmpty)
                              Text(
                                _sectionTitleController.text.trim(),
                                textAlign: TextAlign.center,
                                style: const TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            const SizedBox(height: 12),
                            Align(
                              alignment: Alignment.centerRight,
                              child: Text(
                                _formattedDate,
                                style: const TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.normal,
                                ),
                              ),
                            ),
                            const SizedBox(height: 12),

                            Align(
                              alignment: Alignment.centerLeft,
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  vertical: 6,
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      'To the Owner/Representative:',
                                      style: TextStyle(
                                        fontSize: 10,
                                        fontWeight: FontWeight.bold,
                                        color: context.adaptiveTextDark,
                                      ),
                                    ),
                                    const SizedBox(height: 6),
                                    Text(
                                      _ownerNameController.text.trim().isEmpty
                                          ? '______________________'
                                          : _ownerNameController.text.trim(),
                                      style: TextStyle(
                                        fontSize: 10.5,
                                        fontWeight: FontWeight.bold,
                                        color: context.adaptiveTextDark,
                                      ),
                                    ),
                                    const SizedBox(height: 2),
                                    Text(
                                      _addressController.text.trim().isEmpty
                                          ? '______________________'
                                          : _addressController.text.trim(),
                                      style: TextStyle(
                                        fontSize: 10.5,
                                        color: context.adaptiveTextMid,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                            const SizedBox(height: 8),

                            Container(
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: context.adaptiveBackground,
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Text(
                                _effectiveCertificationText,
                                style: TextStyle(
                                  fontSize: 10,
                                  color: context.adaptiveTextMid,
                                  height: 1.35,
                                ),
                                textAlign: TextAlign.justify,
                              ),
                            ),
                            const SizedBox(height: 12),

                            Align(
                              alignment: Alignment.centerLeft,
                              child: Text(
                                'Maraming salamat po.',
                                style: TextStyle(
                                  fontSize: 10,
                                  color: context.adaptiveTextMid,
                                ),
                              ),
                            ),
                            const SizedBox(height: 12),
                            Align(
                              alignment: Alignment.centerRight,
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.center,
                                children: [
                                  Text(
                                    _closingGreetingController.text.trim().isEmpty
                                        ? 'Lubos na gumagalang,'
                                        : _closingGreetingController.text.trim(),
                                    style: TextStyle(
                                      fontSize: 10,
                                      color: context.adaptiveTextMid,
                                    ),
                                  ),
                                  const SizedBox(height: 24),
                                  Stack(
                                    alignment: Alignment.bottomCenter,
                                    clipBehavior: Clip.none,
                                    children: [
                                      if (_signatureBase64 != null)
                                        Positioned(
                                          bottom: 12,
                                          child: SizedBox(
                                            height: 60,
                                            child: Image.memory(
                                              base64Decode(_signatureBase64!),
                                              fit: BoxFit.contain,
                                            ),
                                          ),
                                        ),
                                      Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.center,
                                        children: [
                                          Text(
                                            _signatoryNameController.text
                                                    .trim()
                                                    .isEmpty
                                                ? '______________________'
                                                : _signatoryNameController.text
                                                      .trim(),
                                            style: const TextStyle(
                                              fontSize: 10,
                                              fontWeight: FontWeight.bold,
                                            ),
                                          ),
                                          const SizedBox(height: 2),
                                          Text(
                                            _signatoryPositionController.text
                                                    .trim()
                                                    .isEmpty
                                                ? '______________________'
                                                : _signatoryPositionController
                                                      .text
                                                      .trim(),
                                            style: const TextStyle(
                                              fontSize: 10,
                                              fontWeight: FontWeight.normal,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),

                            const SizedBox(height: 24),
                            Container(height: 1, color: Colors.grey.shade300),
                            const SizedBox(height: 8),
                            if (_footerTaglineController.text.trim().isNotEmpty)
                              Text(
                                _footerTaglineController.text.trim(),
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontSize: 9,
                                  fontWeight: FontWeight.bold,
                                  color: Colors.blue.shade900,
                                ),
                              ),
                            const SizedBox(height: 2),
                            if (_footerMottoController.text.trim().isNotEmpty)
                              Text(
                                _footerMottoController.text.trim(),
                                textAlign: TextAlign.center,
                                style: GoogleFonts.montserrat(
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                  color: Colors.orange.shade900,
                                  letterSpacing: 1.5,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),

                  // ── Bottom Actions ──
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton.icon(
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppColors.darkGreen,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 14),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          icon: const Icon(Icons.print_rounded),
                          label: const Text('Print Notice'),
                          onPressed: _handlePrint,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: OutlinedButton.icon(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: context.adaptivePrimary,
                            padding: const EdgeInsets.symmetric(vertical: 14),
                            side: BorderSide(
                              color: context.adaptivePrimary,
                              width: 1.5,
                            ),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                          icon: const Icon(Icons.picture_as_pdf),
                          label: const Text('Export PDF Notice'),
                          onPressed: _handleExportPdf,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                ],
              ),
            ),
    );
  }
}

class _SearchModal extends StatefulWidget {
  final List<InspectionTask> tasks;
  final ValueChanged<InspectionTask> onSelected;

  const _SearchModal({required this.tasks, required this.onSelected});

  @override
  State<_SearchModal> createState() => _SearchModalState();
}

class _SearchModalState extends State<_SearchModal> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final filtered = widget.tasks.where((t) {
      final q = _query.toLowerCase();
      return t.detectedName.toLowerCase().contains(q) ||
          t.barangayName.toLowerCase().contains(q);
    }).toList();

    return Container(
      decoration: BoxDecoration(
        color: context.adaptiveSurface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
      ),
      margin: const EdgeInsets.only(top: 60),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: TextField(
              autofocus: true,
              decoration: InputDecoration(
                hintText: 'Search Establishment or Barangay...',
                prefixIcon: const Icon(Icons.search),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                contentPadding: EdgeInsets.zero,
              ),
              onChanged: (val) => setState(() => _query = val),
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: filtered.length,
              itemBuilder: (context, index) {
                final t = filtered[index];
                return ListTile(
                  leading: const Icon(Icons.storefront),
                  title: Text(
                    t.detectedName,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  subtitle: Text(t.barangayName),
                  onTap: () {
                    widget.onSelected(t);
                    Navigator.pop(context);
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
