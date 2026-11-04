"""Build only configured regions; publish a catalogue only after all assets exist."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.request

from build_osm_poi_package import build, selectors_from_catalog
from offline_package_metadata import read_poly

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'catalog/OsmHikingCatalog.kt'
REGIONS = json.loads((ROOT / 'catalog/regions.json').read_text(encoding='utf-8'))
MAX_PACKAGE = 1024 ** 3

def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

def download(url, destination):
    partial = destination.with_suffix(destination.suffix + '.part')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'RutasGen-package-builder/1.0'})
        with urllib.request.urlopen(request, timeout=120) as response, partial.open('wb') as output:
            expected = response.headers.get('Content-Length')
            total = 0
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                total += len(chunk)
                if total % (64 * 1024 * 1024) == 0:
                    print(f'Descargando {destination.name}: {total // (1024*1024)} MiB', flush=True)
        if expected is not None and partial.stat().st_size != int(expected):
            raise ValueError('Descarga incompleta: ' + url)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)

def entry_for(path, repository, tag):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repositorio inválido')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', tag):
        raise ValueError('Versión inválida')
    size = path.stat().st_size
    if not 0 < size <= MAX_PACKAGE:
        raise ValueError('Dividir el paquete: supera el límite del instalador Android')
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite dañado')
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
        if metadata['format'] != 'rutasgen-osm-poi-v1':
            raise ValueError('Formato incompatible')
        coverage = json.loads(metadata['coverage_geojson'])
        if coverage.get('type') != 'MultiPolygon' or not coverage.get('coordinates'):
            raise ValueError('Cobertura ausente')
        count = db.execute('SELECT count(*) FROM pois').fetchone()[0]
        if count == 0:
            raise ValueError('No publicar un país vacío')
    return {
        'id': metadata['package_id'], 'name': metadata['display_name'],
        'country': metadata['country_code'], 'format': metadata['format'],
        'snapshot': metadata['source_snapshot_utc'],
        'catalogSignature': metadata['catalog_signature'],
        'complete': metadata['coverage_complete'] == 'true',
        'coverage': coverage, 'count': count, 'bytes': size, 'sha256': digest(path),
        'url': f'https://github.com/{repository}/releases/download/{tag}/{path.name}',
        'attribution': '© OpenStreetMap contributors · Geofabrik',
        'license': 'https://opendatacommons.org/licenses/odbl/1-0/',
    }

def build_region(region, out):
    extract, name, country = REGIONS[region]
    print(f"INICIO {region}: {name}", flush=True)
    with tempfile.TemporaryDirectory(prefix='rutasgen-extract-') as folder:
        folder = Path(folder)
        source = folder / 'source.osm.pbf'
        boundary = folder / 'coverage.poly'
        download(f'https://download.geofabrik.de/{extract}.poly', boundary)
        download(f'https://download.geofabrik.de/{extract}-latest.osm.pbf', source)
        import osmium
        with osmium.io.Reader(str(source)) as reader:
            snapshot = reader.header().get('osmosis_replication_timestamp')
        if not snapshot:
            raise ValueError('Extracto sin fecha verificable')
        # A superset of every selector, with dependencies retained. Precise AND
        # matching and named-only rules remain in the existing Kotlin-derived DSL.
        expressions = sorted({f'nwr/{key}={value}' for tags, _ in selectors_from_catalog(CATALOG)
                              for key, value in tags.items()})
        filtered = folder / 'selected.osm.pbf'
        print(f"{region}: filtrando geometrías", flush=True)
        subprocess.run(['osmium', 'tags-filter', str(source), *expressions,
                        '-o', str(filtered),
                        '--output-header=osmosis_replication_timestamp=' + snapshot], check=True)
        source.unlink()  # Free raw extract space before building the dependency cache.
        destination = out / f'{region}-poi.sqlite'
        print(f"{region}: construyendo SQLite y resolviendo relaciones", flush=True)
        result = build(filtered, destination, CATALOG, coverage=read_poly(boundary),
                       package_id=region + '-geofabrik', name=name, country=country)
        print(json.dumps({'region': region, **result}), flush=True)
        return destination

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--region', choices=sorted(REGIONS), required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    entries = [entry_for(build_region(region, args.output), args.repository, args.tag)
               for region in [args.region]]
    catalog = {'schema': 'rutasgen-poi-catalog-v1',
               'generatedAt': datetime.now(timezone.utc).isoformat(), 'packages': entries}
    (args.output / 'catalog-v1.json').write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
    (args.output / 'SHA256SUMS').write_text(''.join(
        f'{digest(path)}  {path.name}\n' for path in sorted(args.output.iterdir())
        if path.is_file() and path.name != 'SHA256SUMS'), encoding='utf-8')

if __name__ == '__main__':
    main()
