import 'dart:convert';
import 'dart:math';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'flag_service.dart';

class BoundaryService {
  static final BoundaryService _instance = BoundaryService._internal();
  factory BoundaryService() => _instance;
  BoundaryService._internal();

  /// Default spatial tolerance buffer in meters (accommodates GPS drift and GeoJSON offsets).
  static const double defaultBufferMeters = 100.0;

  // Map of Barangay Name (normalized) -> List of Polygons.
  // Each Polygon is a List of points [lng, lat].
  final Map<String, List<List<List<double>>>> _barangayPolygons = {};
  bool _isLoaded = false;

  Future<void> loadBoundaries() async {
    if (_isLoaded) return;
    try {
      final jsonString = await rootBundle.loadString('assets/data/mataasnakahoy.json');
      final data = jsonDecode(jsonString);
      
      if (data['features'] != null) {
        for (var feature in data['features']) {
          final properties = feature['properties'];
          final geometry = feature['geometry'];
          
          if (properties != null && geometry != null && geometry['type'] == 'MultiPolygon') {
            final String rawName = properties['ADM4_EN']?.toString() ?? '';
            final String normalizedName = _normalizeName(rawName);
            
            final List<dynamic> coords = geometry['coordinates'];
            List<List<List<double>>> polygons = [];
            
            for (var polygon in coords) {
              // We typically only care about the exterior ring (index 0) for simple point-in-polygon
              if (polygon is List && polygon.isNotEmpty) {
                final exteriorRing = polygon[0] as List;
                List<List<double>> points = [];
                for (var point in exteriorRing) {
                  if (point is List && point.length >= 2) {
                    points.add([(point[0] as num).toDouble(), (point[1] as num).toDouble()]);
                  }
                }
                polygons.add(points);
              }
            }
            
            if (normalizedName.isNotEmpty && polygons.isNotEmpty) {
              _barangayPolygons[normalizedName] = polygons;
            }
          }
        }
      }
      _isLoaded = true;
    } catch (e) {
      debugPrint('Error loading boundaries: $e');
    }
  }

  String _normalizeName(String name) {
    // Remove "Brgy.", "Barangay", "(Pob.)", extra spaces, and lowercase
    return name
        .replaceAll(RegExp(r'brgy\.?\s*', caseSensitive: false), '')
        .replaceAll(RegExp(r'barangay\s*', caseSensitive: false), '')
        .replaceAll(RegExp(r'\(Pob\.\)', caseSensitive: false), '')
        .replaceAll('-', ' ')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim()
        .toLowerCase();
  }

  List<List<List<double>>>? getPolygons(String barangayName) {
    if (!_isLoaded || _barangayPolygons.isEmpty) return null;

    final normalized = _normalizeName(barangayName);
    List<List<List<double>>>? polygons = _barangayPolygons[normalized];
    
    if (polygons == null) {
      for (var key in _barangayPolygons.keys) {
        if (key.contains(normalized) || normalized.contains(key)) {
          polygons = _barangayPolygons[key];
          break;
        }
      }
    }
    return polygons;
  }

  /// Returns true if (lat, lng) falls inside ANY Mataasnakahoy barangay polygon,
  /// or within [bufferMeters] distance of any polygon boundary.
  bool isPointInMataasnakahoy(double lat, double lng, {double bufferMeters = defaultBufferMeters}) {
    if (!_isLoaded || _barangayPolygons.isEmpty) return false;
    for (var polygons in _barangayPolygons.values) {
      for (var polygon in polygons) {
        if (_isPointInPolygonWithBuffer(lat, lng, polygon, bufferMeters: bufferMeters)) {
          return true;
        }
      }
    }
    return false;
  }

  /// Returns true if (lat, lng) falls inside the polygon for [barangayName],
  /// or within [bufferMeters] distance of its boundary.
  bool isPointInBarangay(double lat, double lng, String barangayName, {double bufferMeters = defaultBufferMeters}) {
    if (!_isLoaded || _barangayPolygons.isEmpty) return true; // Fail open if boundaries aren't loaded

    final polygons = getPolygons(barangayName);

    if (polygons == null) {
      debugPrint('BoundaryService: Could not match barangay name $barangayName. Failing open.');
      return true; // Could not match barangay name, fail open
    }

    // Check if the point is inside or within buffer of any polygon for this barangay
    for (var polygon in polygons) {
      if (_isPointInPolygonWithBuffer(lat, lng, polygon, bufferMeters: bufferMeters)) {
        return true;
      }
    }
    
    return false;
  }

  /// Find which [Barangay] object from a list of barangays contains (or is closest within buffer to) the given [lat], [lng] point.
  Barangay? findBarangayForPoint(double lat, double lng, List<Barangay> barangays, {double bufferMeters = defaultBufferMeters}) {
    if (!_isLoaded || _barangayPolygons.isEmpty) return null;

    // 1. First pass: exact point-in-polygon containment
    String? matchedKey;
    for (var entry in _barangayPolygons.entries) {
      for (var polygon in entry.value) {
        if (_isPointInPolygon(lat, lng, polygon)) {
          matchedKey = entry.key;
          break;
        }
      }
      if (matchedKey != null) break;
    }

    // 2. Second pass: if exact match fails, check within buffer tolerance
    if (matchedKey == null) {
      double minBufferDist = double.infinity;
      for (var entry in _barangayPolygons.entries) {
        for (var polygon in entry.value) {
          final dist = _distanceToPolygonInMeters(lat, lng, polygon);
          if (dist <= bufferMeters && dist < minBufferDist) {
            minBufferDist = dist;
            matchedKey = entry.key;
          }
        }
      }
    }

    if (matchedKey == null) return null;

    // Match with barangays list
    for (var b in barangays) {
      final norm = _normalizeName(b.name);
      if (norm == matchedKey || norm.contains(matchedKey) || matchedKey.contains(norm)) {
        return b;
      }
    }

    // Roman numeral and digit normalization mapping
    final romanMap = {
      'district i': '1', 'district ii': '2', 'district iii': '3', 'district iv': '4',
      'i': '1', 'ii': '2', 'iii': '3', 'iv': '4', 'ii a': '2', '2 a': '2',
    };
    final keyDigit = romanMap[matchedKey] ?? matchedKey;

    for (var b in barangays) {
      final norm = _normalizeName(b.name);
      final bDigit = romanMap[norm] ?? norm;
      if (bDigit == keyDigit || norm.contains(keyDigit) || keyDigit.contains(norm)) {
        return b;
      }
    }

    return null;
  }

  bool _isPointInPolygonWithBuffer(double lat, double lng, List<List<double>> polygon, {double bufferMeters = defaultBufferMeters}) {
    if (_isPointInPolygon(lat, lng, polygon)) {
      return true;
    }
    final dist = _distanceToPolygonInMeters(lat, lng, polygon);
    return dist <= bufferMeters;
  }

  /// Calculates shortest distance in meters from (lat, lng) to any boundary segment of [polygon].
  double _distanceToPolygonInMeters(double lat, double lng, List<List<double>> polygon) {
    if (polygon.isEmpty) return double.infinity;

    double minDistanceSq = double.infinity;
    const double latToMeters = 110540.0;
    final double lngToMeters = 111320.0 * cos(lat * pi / 180.0);

    final double px = lng * lngToMeters;
    final double py = lat * latToMeters;

    for (int i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      final double ax = polygon[j][0] * lngToMeters;
      final double ay = polygon[j][1] * latToMeters;
      final double bx = polygon[i][0] * lngToMeters;
      final double by = polygon[i][1] * latToMeters;

      final double distSq = _distToSegmentSq(px, py, ax, ay, bx, by);
      if (distSq < minDistanceSq) {
        minDistanceSq = distSq;
      }
    }

    return sqrt(minDistanceSq);
  }

  /// Shortest distance squared from point (px, py) to segment (ax, ay)-(bx, by).
  double _distToSegmentSq(double px, double py, double ax, double ay, double bx, double by) {
    final double l2 = (bx - ax) * (bx - ax) + (by - ay) * (by - ay);
    if (l2 == 0) return (px - ax) * (px - ax) + (py - ay) * (py - ay);
    double t = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / l2;
    t = t.clamp(0.0, 1.0);
    final double projX = ax + t * (bx - ax);
    final double projY = ay + t * (by - ay);
    return (px - projX) * (px - projX) + (py - projY) * (py - projY);
  }

  bool _isPointInPolygon(double lat, double lng, List<List<double>> polygon) {
    bool isInside = false;
    for (int i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      final double xi = polygon[i][0]; // lng
      final double yi = polygon[i][1]; // lat
      final double xj = polygon[j][0]; // lng
      final double yj = polygon[j][1]; // lat

      final bool intersect = ((yi > lat) != (yj > lat)) &&
          (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi);
      if (intersect) isInside = !isInside;
    }
    return isInside;
  }
}

