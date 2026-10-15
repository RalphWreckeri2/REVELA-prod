package ph.gov.mataasnakahoy.revela

import android.content.Context
import android.view.View
import com.google.android.gms.maps.StreetViewPanorama
import com.google.android.gms.maps.StreetViewPanoramaOptions
import com.google.android.gms.maps.StreetViewPanoramaView
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.StreetViewSource
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.StandardMessageCodec
import io.flutter.plugin.platform.PlatformView
import io.flutter.plugin.platform.PlatformViewFactory
import java.util.concurrent.atomic.AtomicBoolean

class StreetViewPanoramaFactory(
    private val context: Context,
    private val messenger: BinaryMessenger,
) : PlatformViewFactory(StandardMessageCodec.INSTANCE) {
    override fun create(context: Context, viewId: Int, args: Any?): PlatformView {
        val arguments = args as? Map<*, *>
            ?: throw IllegalArgumentException("Street View coordinates are required.")
        val latitude = (arguments["latitude"] as? Number)?.toDouble()
            ?: throw IllegalArgumentException("Street View latitude is invalid.")
        val longitude = (arguments["longitude"] as? Number)?.toDouble()
            ?: throw IllegalArgumentException("Street View longitude is invalid.")
        require(
            latitude.isFinite() && longitude.isFinite() &&
                latitude in -90.0..90.0 && longitude in -180.0..180.0,
        ) { "Street View coordinates are outside the valid range." }
        return StreetViewPanoramaPlatformView(
            context = this.context,
            messenger = messenger,
            viewId = viewId,
            position = LatLng(latitude, longitude),
        )
    }

    companion object {
        const val VIEW_TYPE = "revela/streetview-panorama"
    }
}

private class StreetViewPanoramaPlatformView(
    context: Context,
    messenger: BinaryMessenger,
    viewId: Int,
    private val position: LatLng,
) : PlatformView, MethodChannel.MethodCallHandler, EventChannel.StreamHandler {
    private val channelName = "revela/streetview/$viewId"
    private val methodChannel = MethodChannel(messenger, channelName)
    private val eventChannel = EventChannel(messenger, "$channelName/events")
    private val disposed = AtomicBoolean(false)
    private var panorama: StreetViewPanorama? = null
    private var eventSink: EventChannel.EventSink? = null
    private var lastStatus: Map<String, Any> = status("loading")
    private var hasRequestedPosition = false

    private val panoramaView = StreetViewPanoramaView(
        context,
        StreetViewPanoramaOptions()
            .streetNamesEnabled(true)
            .userNavigationEnabled(true)
            .panningGesturesEnabled(true)
            .zoomGesturesEnabled(true),
    )

    init {
        methodChannel.setMethodCallHandler(this)
        eventChannel.setStreamHandler(this)
        panoramaView.onCreate(null)
        panoramaView.getStreetViewPanoramaAsync { streetView ->
            if (disposed.get()) return@getStreetViewPanoramaAsync
            panorama = streetView
            streetView.setOnStreetViewPanoramaChangeListener { location ->
                if (!hasRequestedPosition || disposed.get()) return@setOnStreetViewPanoramaChangeListener
                if (location == null) {
                    publish(status("unavailable"))
                } else {
                    publish(
                        mapOf(
                            "state" to "available",
                            "panoId" to location.panoId,
                            "latitude" to location.position.latitude,
                            "longitude" to location.position.longitude,
                        ),
                    )
                }
            }
            requestPosition()
        }
    }

    override fun getView(): View = panoramaView

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "retry" -> {
                requestPosition()
                result.success(null)
            }
            "resume" -> {
                panoramaView.onResume()
                result.success(null)
            }
            "pause" -> {
                panoramaView.onPause()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
        events?.success(lastStatus)
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
    }

    override fun dispose() {
        if (!disposed.compareAndSet(false, true)) return
        methodChannel.setMethodCallHandler(null)
        eventChannel.setStreamHandler(null)
        eventSink = null
        panoramaView.onPause()
        panoramaView.onDestroy()
        panorama = null
    }

    private fun requestPosition() {
        val streetView = panorama
        if (streetView == null) {
            publish(status("loading"))
            return
        }
        hasRequestedPosition = true
        publish(status("loading"))
        streetView.setPosition(position, SEARCH_RADIUS_METERS, StreetViewSource.OUTDOOR)
    }

    private fun publish(value: Map<String, Any>) {
        lastStatus = value
        eventSink?.success(value)
    }

    private fun status(state: String): Map<String, Any> =
        mapOf("state" to state)

    companion object {
        private const val SEARCH_RADIUS_METERS = 100
    }
}
