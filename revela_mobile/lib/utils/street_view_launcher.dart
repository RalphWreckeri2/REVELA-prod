import 'package:url_launcher/url_launcher.dart';

Future<bool> launchGoogleStreetView(double latitude, double longitude) {
  final uri = Uri.https('www.google.com', '/maps/@', {
    'api': '1',
    'map_action': 'pano',
    'viewpoint': '$latitude,$longitude',
  });
  return launchUrl(uri, mode: LaunchMode.externalApplication);
}
