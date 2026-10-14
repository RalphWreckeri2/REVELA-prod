import java.util.Properties
import java.io.FileInputStream
import java.net.URI

plugins {
    id("com.android.application")
    id("kotlin-android")
    id("dev.flutter.flutter-gradle-plugin")
}

val localProperties = Properties()
val localPropertiesFile = rootProject.file("local.properties")
if (localPropertiesFile.exists()) {
    localPropertiesFile.reader().use { reader ->
        localProperties.load(reader)
    }
}
val mapsApiKey = localProperties.getProperty("GOOGLE_MAPS_API_KEY")?.trim().orEmpty()

// ── Signing config for release builds ──
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

val qaApiBase = providers.gradleProperty("qaApiBase").orNull?.trim().orEmpty()
if (qaApiBase.isNotEmpty()) {
    val qaUri = runCatching { URI(qaApiBase) }.getOrNull()
        ?: error("qaApiBase must be an explicit local HTTP backend URL.")
    val host = qaUri.host?.lowercase()
        ?: error("qaApiBase must include a local host.")
    val parts = host.split(".")
    val privateIpv4 = parts.size == 4 && parts.all { it.toIntOrNull() in 0..255 } &&
        (parts[0] == "10" ||
            (parts[0] == "172" && parts[1].toInt() in 16..31) ||
            (parts[0] == "192" && parts[1] == "168"))
    require(
        qaUri.scheme == "http" &&
            qaUri.userInfo == null &&
            qaUri.query == null &&
            qaUri.fragment == null &&
            (qaUri.path.isNullOrEmpty() || qaUri.path == "/") &&
            qaUri.port in 1..65535 &&
            (host == "localhost" || host == "127.0.0.1" ||
                host == "10.0.2.2" || privateIpv4),
    ) {
        "qaApiBase must be an explicit local HTTP backend URL, such as " +
            "http://10.0.2.2:5000. Production and public hosts are not allowed."
    }
}

android {
    namespace = "ph.gov.mataasnakahoy.revela"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        isCoreLibraryDesugaringEnabled = true
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    defaultConfig {
        applicationId = "ph.gov.mataasnakahoy.revela"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        resValue("string", "app_name", "REVELA")
        manifestPlaceholders["GOOGLE_MAPS_API_KEY"] = mapsApiKey.ifEmpty { "DEFAULT_KEY" }
    }

    flavorDimensions += "environment"
    productFlavors {
        create("production") {
            dimension = "environment"
        }
        create("qa") {
            dimension = "environment"
            applicationIdSuffix = ".qa"
            resValue("string", "app_name", "REVELA QA")
            manifestPlaceholders["QA_API_BASE"] = qaApiBase
        }
    }

    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                keyAlias = keystoreProperties["keyAlias"] as? String ?: ""
                keyPassword = keystoreProperties["keyPassword"] as? String ?: ""
                storeFile = (keystoreProperties["storeFile"] as? String)?.let { file(it) }
                storePassword = keystoreProperties["storePassword"] as? String ?: ""
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }


}

flutter {
    source = "../.."
}

val verifyProductionMapsKey by tasks.registering {
    group = "verification"
    description = "Validates the Maps key and release signing configuration."
    doLast {
        if (mapsApiKey.isEmpty() || mapsApiKey == "DEFAULT_KEY") {
            throw GradleException(
                "Production release requires GOOGLE_MAPS_API_KEY in android/local.properties."
            )
        }

        val requiredSigningProperties = listOf(
            "keyAlias",
            "keyPassword",
            "storeFile",
            "storePassword",
        )
        val missingSigningProperties = requiredSigningProperties.filter {
            keystoreProperties.getProperty(it)?.isNotBlank() != true
        }
        if (!keystorePropertiesFile.exists() || missingSigningProperties.isNotEmpty()) {
            throw GradleException(
                "Production release requires android/key.properties with the intended " +
                    "APK signing identity. Missing: " +
                    (missingSigningProperties.ifEmpty { listOf("key.properties") }
                        .joinToString(", "))
            )
        }

        val keystorePath = keystoreProperties.getProperty("storeFile").trim()
        val keystore = file(keystorePath)
        if (!keystore.isFile) {
            throw GradleException(
                "Production release keystore does not exist: $keystorePath"
            )
        }
    }
}

tasks.matching { it.name == "assembleProductionRelease" }.configureEach {
    dependsOn(verifyProductionMapsKey)
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
    implementation("com.google.android.gms:play-services-maps:20.0.0")
}

// Firebase configuration: Apply the Google Services plugin whenever google-services.json exists.
val googleServicesConfig = file("google-services.json")
if (googleServicesConfig.exists()) {
    apply(plugin = "com.google.gms.google-services")
    tasks.configureEach {
        if (name.startsWith("processQa") && name.endsWith("GoogleServices")) {
            enabled = false
        }
    }
} else {
    logger.warn(
        "google-services.json not found at ${googleServicesConfig.path}; " +
            "Firebase Android services are disabled.",
    )
}
