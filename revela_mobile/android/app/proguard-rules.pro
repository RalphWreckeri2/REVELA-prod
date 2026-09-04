# Flutter Wrapper
-keep class io.flutter.app.** { *; }
-keep class io.flutter.plugin.** { *; }
-keep class io.flutter.util.** { *; }
-keep class io.flutter.view.** { *; }
-keep class io.flutter.embedding.** { *; }
-keep class io.flutter.provider.** { *; }
-keep class io.flutter.plugin.editing.** { *; }

# Flutter Plugins & JNI
-keepclasseswithmembernames class * {
    native <methods>;
}

-keepclassmembers class * extends enum {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# Dio HTTP library
-keep class com.bugsnag.** { *; }
-keepattributes Signature
-keepattributes InnerClasses
-keepattributes *Annotation*

# Firebase & Google Play Services
-keep class com.google.firebase.** { *; }
-keep class com.google.android.gms.** { *; }

# Sqflite
-keep class com.tekartik.sqflite.** { *; }

# Local Auth / Biometrics
-keep class androidx.biometric.** { *; }
-keep class io.flutter.plugins.localauth.** { *; }

# Flutter Secure Storage
-keep class com.it_neXt.flutter_secure_storage.** { *; }

# Google Maps
-keep class com.google.android.gms.maps.** { *; }
-keep class com.google.android.gms.location.** { *; }

# Printing & PDF
-keep class net.nfet.flutter.printing.** { *; }

# Prevent shrinking of generated Flutter code
-dontwarn io.flutter.embedding.**
-dontwarn com.google.firebase.**
