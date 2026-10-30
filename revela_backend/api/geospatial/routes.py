from flask import Blueprint, jsonify, request

from api.analytics.hotspots import HOTSPOT_POPULATIONS, HOTSPOT_POPULATION_OBJECTIVE
from api.flags.service import get_hotspot_cluster_payload
from api.middleware.decorators import jwt_required

geospatial_bp = Blueprint("geospatial", __name__)


@geospatial_bp.route("/diagnostics/clusters", methods=["GET"])
@jwt_required()
def diagnostic_clusters_route():
    """Return shared DBSCAN results for the selected population."""
    population = (
        request.args.get("population") or HOTSPOT_POPULATION_OBJECTIVE
    ).strip()
    if population not in HOTSPOT_POPULATIONS:
        return jsonify({"error": "Unknown DBSCAN population."}), 400
    payload, error = get_hotspot_cluster_payload(population)
    if error:
        return jsonify({"error": error}), 500
    return jsonify(payload), 200
