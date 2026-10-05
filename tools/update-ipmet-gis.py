import hashlib
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image


IPMET = "https://www.ipmetradar.com.br"
GIS_PAGE = f"{IPMET}/mobile2/openlayers/ipmet/radar.php"
WMS_URL = f"{IPMET}/cgi-bin/mapserv.fcgi"
TITAN_URL = f"{IPMET}/mobile2/openlayers/ipmet/share/alerta2.php"
STATE_URL = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/main/public/data/brazil-states.geojson"
WMS_BOUNDS = [-55.650833, -26.001944, -44.535004, -18.516675]
FRAME_LIMIT = 12


def fetch(url, referer, accept="*/*"):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Referer": referer,
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.headers.get_content_type(), response.read()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _png_bytes(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main(output_directory):
    output = Path(output_directory)
    frames_directory = output / "frames"
    frames_directory.mkdir(parents=True, exist_ok=True)

    _, gis_html = fetch(GIS_PAGE, GIS_PAGE, "text/html")
    match = re.search(rb"var\s+data_hora\s*=\s*['\"]([^'\"]+)", gis_html)
    if match is None:
        raise SystemExit("Não foi possível ler o horário atual do GIS oficial do IPMET.")
    radar_time = match.group(1).decode("ascii")

    wms_query = urllib.parse.urlencode(
        {
            "map": "/home/webadm/alerta/dados/ppi/ultimo.map",
            "layers": "merged",
            "styles": "",
            "transparent": "true",
            "alpha": "true",
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "srs": "EPSG:4326",
            "bbox": ",".join(map(str, WMS_BOUNDS)),
            "width": "1100",
            "height": "740",
            "format": "image/png",
        }
    )
    image_type, radar_image = fetch(
        f"{WMS_URL}?{wms_query}", f"{IPMET}/2mobileGis.php", "image/png"
    )
    if image_type != "image/png" or not radar_image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit(f"O WMS do IPMET não retornou um PNG válido ({image_type}).")

    _, official_animation = fetch(
        f"{IPMET}/img-ppi/ppi-anim.gif", f"{IPMET}/2animRadar.php", "image/gif"
    )
    with Image.open(BytesIO(official_animation)) as gif:
        if gif.format != "GIF" or gif.width < 812 or gif.height < 448:
            raise SystemExit("O produto oficial do IPMET mudou; não foi possível validar a legenda dBZ.")
        gif.seek(0)
        legend = gif.convert("RGB").crop((750, 226, 751, 394))
        legend = legend.transpose(Image.Transpose.ROTATE_270)
        legend = legend.resize((720, 14), Image.Resampling.BICUBIC)
    (output / "legend.png").write_bytes(_png_bytes(legend))

    titan_query = urllib.parse.urlencode({"data_hora": radar_time})
    _, titan_data = fetch(
        f"{TITAN_URL}?{titan_query}", GIS_PAGE, "application/json"
    )
    alerts = json.loads(titan_data)
    if alerts.get("type") != "FeatureCollection" or not isinstance(alerts.get("features"), list):
        raise SystemExit("O feed TITAN do IPMET não retornou um GeoJSON FeatureCollection válido.")

    _, states_data = fetch(STATE_URL, GIS_PAGE, "application/geo+json, application/json")
    states = json.loads(states_data)
    sao_paulo = next(
        (
            feature
            for feature in states.get("features", [])
            if feature.get("properties", {}).get("sigla") == "SP"
        ),
        None,
    )
    if sao_paulo is None:
        raise SystemExit("Não foi possível obter a geometria do estado de São Paulo.")
    (output / "sao-paulo.geojson").write_bytes(json_bytes(sao_paulo))

    coordinates = sao_paulo["geometry"]["coordinates"]
    longitudes = []
    latitudes = []
    for polygon in coordinates:
        for ring in polygon:
            for longitude, latitude in ring:
                longitudes.append(longitude)
                latitudes.append(latitude)
    sao_paulo_bounds = [
        [min(latitudes), min(longitudes)],
        [max(latitudes), max(longitudes)],
    ]

    signature = hashlib.sha256(radar_image + json_bytes(alerts)).hexdigest()
    frames = []
    index_path = output / "frames.json"
    if index_path.is_file():
        try:
            frames = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            frames = []

    if not frames or frames[-1].get("signature") != signature:
        captured_at = datetime.now(timezone.utc).isoformat()
        filename = f"{radar_time.replace('_', '-')}-{signature[:10]}"
        image_name = f"{filename}.png"
        alerts_name = f"{filename}.geojson"
        (frames_directory / image_name).write_bytes(radar_image)
        (frames_directory / alerts_name).write_bytes(json_bytes(alerts))
        frames.append(
            {
                "image": f"frames/{image_name}",
                "alerts": f"frames/{alerts_name}",
                "radarTime": radar_time,
                "capturedAt": captured_at,
                "signature": signature,
            }
        )

    frames = frames[-FRAME_LIMIT:]
    keep = {Path(frame[key]).name for frame in frames for key in ("image", "alerts")}
    for path in frames_directory.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()

    index_path.write_text(json.dumps(frames, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "source": GIS_PAGE,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "radarTime": radar_time,
        "bounds": [[WMS_BOUNDS[1], WMS_BOUNDS[0]], [WMS_BOUNDS[3], WMS_BOUNDS[2]]],
        "saoPauloBounds": sao_paulo_bounds,
        "saoPauloGeoJSON": "sao-paulo.geojson",
        "legend": "legend.png",
        "alerts": alerts,
        "frames": [
            {key: value for key, value in frame.items() if key != "signature"}
            for frame in frames
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    public_directory = Path(sys.argv[2])
    if public_directory.exists():
        shutil.rmtree(public_directory)
    shutil.copytree(output, public_directory)
    print(
        f"Radar {radar_time}; {len(alerts['features'])} células TITAN; "
        f"{len(frames)} quadros distintos no histórico."
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Uso: update-ipmet-gis.py CACHE_DIR PUBLIC_RADAR_DIR")
    main(sys.argv[1])