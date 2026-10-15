package ph.gov.mataasnakahoy.revela

import android.content.pm.PackageManager
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterFragmentActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        flutterEngine.platformViewsController.registry.registerViewFactory(
            StreetViewPanoramaFactory.VIEW_TYPE,
            StreetViewPanoramaFactory(this, flutterEngine.dartExecutor.binaryMessenger),
        )
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "revela/build_config",
        ).setMethodCallHandler { call, result ->
            if (call.method != "getBuildConfig") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val appInfo = packageManager.getApplicationInfo(
                packageName,
                PackageManager.GET_META_DATA,
            )
            result.success(
                mapOf(
                    "packageName" to packageName,
                    "qaMode" to (packageName.endsWith(".qa")),
                    "qaApiBase" to appInfo.metaData?.getString("revela.qa_api_base"),
                ),
            )
        }
    }
}
