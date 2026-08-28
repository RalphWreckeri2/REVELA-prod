from flask import Blueprint, jsonify

from api.flags.service import get_red_flag_clusters
from api.middleware.decorators import jwt_required

geospatial_bp = Blueprint("geospatial", __name__)


@geospatial_bp.route("/diagnostics/clusters", methods=["GET"])
@jwt_required()
def diagnostic_clusters_route():
    """Return DBSCAN-derived Red Flag hotspot clusters for map diagnostics."""
    clusters, error = get_red_flag_clusters()
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"clusters": clusters}), 200
