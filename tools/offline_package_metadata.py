"""Coverage comes from the extract boundary, never from the locations of its POIs."""
import hashlib
import json
import math
from pathlib import Path

def catalog_signature(selectors):
    expressions = [''.join(f'["{key}"="{value}"]' for key, value in tags.items()) +
                   ('["name"]' if named else '') for tags, named in selectors]
    return hashlib.sha256('\n'.join(sorted(set(expressions))).encode()).hexdigest()

def inside(point, ring):
    x, y = point
    result = False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            result = not result
    return result

def read_poly(path):
    lines = Path(path).read_text().splitlines()
    outers, holes = [], []
    i = 1
    while i < len(lines):
        name = lines[i].strip(); i += 1
        if name == 'END': break
        if not name: continue
        ring = []
        while i < len(lines) and lines[i].strip() != 'END':
            point = list(map(float, lines[i].split())); i += 1
            if len(point) != 2 or not all(math.isfinite(v) for v in point) or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                raise ValueError('Coordenada de cobertura no válida')
            ring.append(point)
        if i >= len(lines): raise ValueError('Polígono sin terminar')
        i += 1
        if len(ring) < 3: raise ValueError('Anillo sin suficientes vértices')
        if ring[0] != ring[-1]: ring.append(ring[0])
        if any(abs(a[0]-b[0]) > 180 for a,b in zip(ring,ring[1:])):
            raise ValueError('Dividir polígonos que cruzan el antimeridiano')
        (holes if name.startswith('!') else outers).append(ring)
    if not outers: raise ValueError('Cobertura vacía')
    polygons = [[ring] for ring in outers]
    for hole in holes:
        owners = [polygon for polygon in polygons if inside(hole[0], polygon[0])]
        if len(owners) != 1: raise ValueError('Hueco de cobertura ambiguo')
        owners[0].append(hole)
    return {'type':'MultiPolygon','coordinates':polygons}

def attach_metadata(db, *, selectors, coverage=None, package_id=None, name=None, country=None, skipped=None):
    values = [('catalog_signature',catalog_signature(selectors))]
    if coverage is not None:
        if not package_id or not name or not country: raise ValueError('Faltan identidad/nombre/país del paquete')
        values += [('coverage_schema','rutasgen-coverage-v1'),('coverage_geojson',json.dumps(coverage,separators=(',',':'))),
                   ('coverage_complete','true' if not any((skipped or {}).values()) else 'false'),
                   ('package_id',package_id),('display_name',name),('country_code',country)]
    db.executemany('INSERT OR REPLACE INTO metadata VALUES (?,?)', values)
