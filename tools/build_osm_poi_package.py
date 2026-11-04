#!/usr/bin/env python3
"""Build an offline SQLite POI package from an OSM extract (no Overpass/API key)."""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from offline_package_metadata import attach_metadata, read_poly
from osm_relation_cache import OsmGeometryCache, ResolutionError, resolve_relation
import tempfile
from contextlib import closing

FORMAT = 'rutasgen-osm-poi-v1'

def selectors_from_catalog(path):
    """Read the project's small Kotlin selector DSL; refuse unsupported syntax."""
    source = Path(path).read_text(encoding='utf-8')
    blocks = re.findall(r'e\(PoiCategory\.(\w+),(.*?)(?=\n        e\(PoiCategory|\n    \))', source, re.S)
    if not blocks:
        raise ValueError('No se reconoce OsmHikingCatalog.kt')
    selectors = []
    for category, block in blocks:
        if 'automatic = false' in block:
            continue
        found = re.findall(r's\((.*?)\)', block, re.S)
        if not found:
            raise ValueError('Categoría automática sin selectores: ' + category)
        for expression in found:
            tags = dict(re.findall(r'"([^"\n]+)"\s+to\s+"([^"\n]+)"', expression))
            if not tags:
                raise ValueError('Selector no reconocido: ' + expression)
            selectors.append((tags, 'named = true' in expression))
    return selectors

def matches(tags, selectors):
    return any(all(tags.get(k) == v for k, v in values.items()) and
               (not named or tags.get('name', '').strip()) for values, named in selectors)

def coordinates(element):
    if element['type'] == 'node':
        return [(element['lat'], element['lon'])]
    if 'geometry' in element:
        return [(p['lat'], p['lon']) for p in element['geometry']]
    return [p for m in element.get('members', []) for p in coordinates(m)]

def insert_element(db, element):
    points = coordinates(element)
    if not points or any(not math.isfinite(lat) or not math.isfinite(lon) or
                         not -90 <= lat <= 90 or not -180 <= lon <= 180 for lat, lon in points):
        return False
    latitudes, longitudes = zip(*points)
    if element['type'] != 'node':
        element['center'] = {'lat': (min(latitudes) + max(latitudes))/2,
                             'lon': (min(longitudes) + max(longitudes))/2}
    db.execute('INSERT OR REPLACE INTO pois VALUES (?,?,?,?,?,?)', (
        f"{element['type']}/{element['id']}", min(latitudes), max(latitudes),
        min(longitudes), max(longitudes), json.dumps(element, ensure_ascii=False, separators=(',', ':'))))
    return True

def create_schema(db, source):
    db.executescript('''
    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE pois (id TEXT PRIMARY KEY, min_lat REAL NOT NULL, max_lat REAL NOT NULL,
                       min_lon REAL NOT NULL, max_lon REAL NOT NULL, element TEXT NOT NULL);
    CREATE INDEX poi_latitude ON pois(min_lat, max_lat);
    CREATE INDEX poi_longitude ON pois(min_lon, max_lon);
    ''')
    db.executemany('INSERT INTO metadata VALUES (?,?)', [
        ('format', FORMAT), ('source', source), ('attribution', '© OpenStreetMap contributors'),
        ('license', 'https://opendatacommons.org/licenses/odbl/1-0/'),
        ('created_utc', datetime.datetime.now(datetime.timezone.utc).isoformat())])

def build(input_path, output_path, catalog_path, index='flex_mem', *, coverage=None, package_id=None, name=None, country=None):
    # index is retained for call compatibility; the cache now resides in SQLite.
    selectors = selectors_from_catalog(catalog_path)
    output_path = Path(output_path)
    if Path(input_path).resolve() == output_path.resolve():
        raise ValueError('Input and output must differ')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    skipped = {'incomplete_nodes': 0, 'incomplete_ways': 0, 'incomplete_relations': 0}
    reasons = {}
    with tempfile.TemporaryDirectory(prefix='rutasgen-osm-', dir=output_path.parent) as folder:
        temporary = Path(folder) / 'package.sqlite'
        with OsmGeometryCache(Path(folder) / 'dependencies.sqlite') as cache:
            cache.read(input_path, lambda tags: matches(tags, selectors))
            with closing(sqlite3.connect(temporary)) as db:
                create_schema(db, Path(input_path).name)
                if cache.snapshot:
                    db.execute('INSERT INTO metadata VALUES (?,?)', ('source_snapshot_utc', cache.snapshot))
                db.execute('INSERT INTO metadata VALUES (?,?)', ('catalog_sha256', hashlib.sha256(Path(catalog_path).read_bytes()).hexdigest()))
                for kind, identifier, tags in cache.selected():
                    try:
                        if kind == 'node':
                            element = cache.node(identifier)
                        elif kind == 'way':
                            element = cache.way(identifier)
                        else:
                            element = resolve_relation(cache, identifier)
                        element['tags'] = json.loads(tags)
                        if not insert_element(db, element):
                            raise ResolutionError('invalid_geometry', identifier)
                    except ResolutionError as error:
                        skipped['incomplete_' + {'node':'nodes', 'way':'ways', 'relation':'relations'}[kind]] += 1
                        reasons[error.reason] = reasons.get(error.reason, 0) + 1
                count = db.execute('SELECT count(*) FROM pois').fetchone()[0]
                db.executemany('INSERT INTO metadata VALUES (?,?)', [(k, str(v)) for k, v in skipped.items()])
                db.execute('INSERT INTO metadata VALUES (?,?)', ('resolution_failures', json.dumps(reasons, sort_keys=True)))
                attach_metadata(db, selectors=selectors, coverage=coverage, package_id=package_id, name=name, country=country, skipped=skipped)
                db.commit()
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite integrity check failed')
            temporary.replace(output_path)
    return {'pois': count, **skipped}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='Extracto .osm.pbf o .osm de Geofabrik/OSM')
    parser.add_argument('output', help='Paquete .sqlite con nombre versionado')
    parser.add_argument('--catalog', default='app/src/main/java/com/example/domain/model/OsmHikingCatalog.kt')
    parser.add_argument('--index', default='flex_mem', help='Compatibilidad con comandos antiguos; ahora se usa caché SQLite temporal')
    parser.add_argument('--coverage-poly', help='Límite .poly que corresponde exactamente al extracto')
    parser.add_argument('--package-id')
    parser.add_argument('--name')
    parser.add_argument('--country')
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output, args.catalog, args.index, coverage=read_poly(args.coverage_poly) if args.coverage_poly else None, package_id=args.package_id, name=args.name, country=args.country), ensure_ascii=False))
