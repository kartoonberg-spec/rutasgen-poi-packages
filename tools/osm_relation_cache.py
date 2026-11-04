"""One OSM read, disk-backed dependencies, bounded expansion of relation trees.

For current-state extracts, not .osc/history. This preserves member geometry; it
is NOT a multipolygon assembler and does not invent missing coordinates.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3


class ResolutionError(ValueError):
    def __init__(self, reason, identifier):
        self.reason = reason
        self.identifier = identifier
        super().__init__(f'{reason}: {identifier}')


@dataclass(frozen=True)
class Limits:
    max_depth: int = 32
    max_members: int = 10_000
    max_objects: int = 10_000
    max_points: int = 100_000
    max_tags_bytes: int = 65_536

    def __post_init__(self):
        if any(value < 1 for value in vars(self).values()):
            raise ValueError('All limits must be positive')


class OsmGeometryCache:
    def __init__(self, path, limits=None):
        self.limits = limits or Limits()
        # Caller supplies a NEW temporary file, never a production POI database.
        if Path(path).exists():
            raise FileExistsError(path)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA cache_size=-8192')  # SQLite page cache ~8 MiB; not a total RAM cap.
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.executescript('''
            CREATE TABLE nodes(id INTEGER PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL);
            CREATE TABLE ways(id INTEGER PRIMARY KEY, refs TEXT NOT NULL, error TEXT);
            CREATE TABLE relations(id INTEGER PRIMARY KEY, tags TEXT NOT NULL, members TEXT NOT NULL, error TEXT);
            CREATE TABLE selected(kind TEXT NOT NULL, id INTEGER NOT NULL, tags TEXT NOT NULL,
                                  PRIMARY KEY(kind,id));
            CREATE TABLE way_geometries(id INTEGER PRIMARY KEY, geometry TEXT NOT NULL);
        ''')
        self.snapshot = None
        self.ready = False

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def read(self, input_path, matches):
        """Exactly one reader/apply. Dependencies may occur BEFORE or AFTER parents."""
        import osmium
        if self.ready:
            raise ValueError('Cache already imported')
        cache = self
        count = 0

        class Handler(osmium.SimpleHandler):
            def tick(self, obj):
                nonlocal count
                if obj.deleted:
                    raise ValueError('Expected current-state extract, not deletion/history input')
                count += 1
                if count % 50_000 == 0:
                    cache.db.commit()

            def selection(self, obj, kind):
                tags = dict(obj.tags)  # Copy now: osmium views expire after callback.
                chosen = matches(tags)
                encoded = json.dumps(tags, ensure_ascii=False, separators=(',', ':')) if chosen or kind == 'relation' else '{}'
                if len(encoded.encode('utf-8')) > cache.limits.max_tags_bytes:
                    raise ValueError(f'Tags exceed configured limit: {kind}/{obj.id}')
                if chosen:
                    cache.db.execute('INSERT INTO selected VALUES(?,?,?)', (kind, int(obj.id), encoded))
                return encoded

            def node(self, obj):
                self.tick(obj)
                self.selection(obj, 'node')
                if obj.location.valid():
                    cache.db.execute('INSERT INTO nodes VALUES(?,?,?)',
                                     (int(obj.id), float(obj.location.lat), float(obj.location.lon)))

            def way(self, obj):
                self.tick(obj)
                self.selection(obj, 'way')
                error = 'point_limit' if len(obj.nodes) > cache.limits.max_points else None
                refs = [] if error else [int(n.ref) for n in obj.nodes]
                cache.db.execute('INSERT INTO ways VALUES(?,?,?)', (int(obj.id), json.dumps(refs), error))

            def relation(self, obj):
                self.tick(obj)
                tags = self.selection(obj, 'relation')
                error = 'member_limit' if len(obj.members) > cache.limits.max_members else None
                members = [] if error else [(str(m.type), int(m.ref), str(m.role)) for m in obj.members
                                            if m.role not in ('approach', 'descent')]
                cache.db.execute('INSERT INTO relations VALUES(?,?,?,?)',
                                 (int(obj.id), tags, json.dumps(members), error))

        try:
            with osmium.io.Reader(str(input_path)) as reader:
                self.snapshot = reader.header().get('osmosis_replication_timestamp')
                osmium.apply(reader, Handler())
            self.db.commit()
            self.ready = True
        except sqlite3.IntegrityError as error:
            raise ValueError('Duplicate OSM IDs: expected a current-state extract, not history') from error

    def node(self, identifier):
        row = self.db.execute('SELECT lat,lon FROM nodes WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ResolutionError('missing_node', identifier)
        return {'type': 'node', 'id': identifier, 'lat': row[0], 'lon': row[1]}

    def way(self, identifier):
        row = self.db.execute('SELECT geometry FROM way_geometries WHERE id=?', (identifier,)).fetchone()
        if row is not None:
            return {'type': 'way', 'id': identifier, 'geometry': json.loads(row[0])}
        row = self.db.execute('SELECT refs,error FROM ways WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ResolutionError('missing_way', identifier)
        if row[1]:
            raise ResolutionError(row[1], identifier)
        refs = json.loads(row[0])
        if not refs:
            raise ResolutionError('empty_way', identifier)
        locations = {}
        # Batch lookups; preserve original order and repeated endpoints afterwards.
        unique = list(dict.fromkeys(refs))
        for start in range(0, len(unique), 500):
            chunk = unique[start:start + 500]
            marks = ','.join('?' for _ in chunk)
            locations.update((i, (lat, lon)) for i, lat, lon in self.db.execute(
                f'SELECT id,lat,lon FROM nodes WHERE id IN ({marks})', chunk))
        if len(locations) != len(unique):
            raise ResolutionError('missing_way_node', identifier)
        geometry = [{'lat': locations[i][0], 'lon': locations[i][1]} for i in refs]
        encoded = json.dumps(geometry, separators=(',', ':'))
        self.db.execute('INSERT INTO way_geometries VALUES(?,?)', (identifier, encoded))
        return {'type': 'way', 'id': identifier, 'geometry': geometry}

    def relation(self, identifier):
        row = self.db.execute('SELECT tags,members,error FROM relations WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ResolutionError('missing_relation', identifier)
        if row[2]:
            raise ResolutionError(row[2], identifier)
        members = json.loads(row[1])
        if not members:
            raise ResolutionError('empty_relation', identifier)
        return json.loads(row[0]), members

    def selected(self):
        # Streaming cursor: do not load a national catalogue into a Python list.
        yield from self.db.execute('SELECT kind,id,tags FROM selected ORDER BY kind,id')


def resolve_relation(cache, identifier):
    """Iterative DFS. active is the CURRENT path, not a global visited set.

    Shared descendants in separate branches are valid. Cycles, missing members and
    limit overflows reject the whole root. No truncated subtree is cached as success.
    Geometry cache lives on disk. Repeated tree occurrences count against budgets
    because the compatible JSON format must expand them again.
    """
    if not cache.ready:
        raise ValueError('Finish reading the extract before resolving references')
    limits = cache.limits
    active = set()
    objects = 0
    points = 0

    def charge(point_count=0):
        nonlocal objects, points
        objects += 1
        points += point_count
        if objects > limits.max_objects or points > limits.max_points:
            raise ResolutionError('expansion_limit', identifier)

    def enter(ref, role=None):
        if ref in active:
            raise ResolutionError('cycle', ref)
        if len(active) >= limits.max_depth:
            raise ResolutionError('depth_limit', ref)
        charge()
        tags, members = cache.relation(ref)
        element = {'type': 'relation', 'id': ref, 'tags': tags, 'members': []}
        if role is not None:
            element['role'] = role
        active.add(ref)
        return [ref, element, iter(members)]

    root = enter(identifier)
    stack = [root]
    while stack:
        frame = stack[-1]
        member = next(frame[2], None)
        if member is None:
            active.remove(frame[0])
            stack.pop()
            if stack:
                stack[-1][1]['members'].append(frame[1])
            continue
        kind, ref, role = member
        if kind == 'r':
            stack.append(enter(ref, role))
        else:
            if kind == 'n':
                item = cache.node(ref)
                charge(1)
            elif kind == 'w':
                item = cache.way(ref)
                charge(len(item['geometry']))
            else:
                raise ResolutionError('unknown_member', ref)
            item['role'] = role
            frame[1]['members'].append(item)
    return root[1]
