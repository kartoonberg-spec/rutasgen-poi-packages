"""Compatibility entry point for old callers; one OSM pass per invocation.

The new builder uses its already-populated cache directly and does not call this.
Calling this from the old builder does NOT make that whole old pipeline single-pass.
"""
from pathlib import Path
import tempfile
from osm_relation_cache import OsmGeometryCache, ResolutionError, resolve_relation


def repair_nested_relations(input_path, db, selectors, index, insert_element):
    from build_osm_poi_package import matches
    remaining = 0
    with tempfile.TemporaryDirectory(prefix='rutasgen-relations-') as folder:
        with OsmGeometryCache(Path(folder) / 'dependencies.sqlite') as cache:
            cache.read(input_path, lambda tags: matches(tags, selectors))
            for kind, identifier, _ in cache.selected():
                if kind != 'relation' or db.execute('SELECT 1 FROM pois WHERE id=?',
                                                    (f'relation/{identifier}',)).fetchone():
                    continue
                try:
                    result = resolve_relation(cache, identifier)
                    if not insert_element(db, result):
                        remaining += 1
                except ResolutionError:
                    remaining += 1
    return remaining
