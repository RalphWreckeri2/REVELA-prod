import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_image_compress/flutter_image_compress.dart';
import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';

/// Utility helper for image compression and resizing.
class ImageCompressor {
  /// Compresses a raw [File] to maximum [maxWidth] x [maxHeight] pixels
  /// and [quality] (default 70).
  ///
  /// Prints debug log: "Original size: $originalSize KB -> Compressed size: $compressedSize KB"
  static Future<File> compressImageFile(
    File file, {
    int maxWidth = 1280,
    int maxHeight = 1280,
    int quality = 70,
  }) async {
    try {
      if (!await file.exists()) {
        return file;
      }

      final originalBytes = await file.length();
      final originalSize = (originalBytes / 1024).toStringAsFixed(2);

      final tempDir = await getTemporaryDirectory();
      final extension = path.extension(file.path).isNotEmpty
          ? path.extension(file.path)
          : '.jpg';
      final targetFileName =
          'compressed_${DateTime.now().millisecondsSinceEpoch}$extension';
      final targetPath = path.join(tempDir.path, targetFileName);

      final XFile? compressedXFile = await FlutterImageCompress.compressAndGetFile(
        file.absolute.path,
        targetPath,
        minWidth: maxWidth,
        minHeight: maxHeight,
        quality: quality,
      );

      if (compressedXFile != null) {
        final compressedFile = File(compressedXFile.path);
        final compressedBytes = await compressedFile.length();
        final compressedSize = (compressedBytes / 1024).toStringAsFixed(2);

        final logMsg =
            'Original size: $originalSize KB -> Compressed size: $compressedSize KB';
        // ignore: avoid_print
        print(logMsg);
        debugPrint(logMsg);

        return compressedFile;
      }
    } catch (e) {
      debugPrint('Error during image compression: $e');
    }

    return file;
  }
}

/// Standalone top-level helper function as requested in requirements.
Future<File> compressImageFile(
  File file, {
  int maxWidth = 1280,
  int maxHeight = 1280,
  int quality = 70,
}) {
  return ImageCompressor.compressImageFile(
    file,
    maxWidth: maxWidth,
    maxHeight: maxHeight,
    quality: quality,
  );
}
