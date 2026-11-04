import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import osmium
from osm_relation_cache import OsmGeometryCache, Limits, ResolutionError, resolve_relation
from build_osm_poi_package import build

CATALOG = Path(__file__).resolve().parents[1] / 'catalog/OsmHikingCatalog.kt'


def relation(identifier, members, selected=False):
    body = ''.join(f'<member type="{kind}" ref="{ref}" role="{role}"/>' for kind, ref, role in members)
    return f'<relation id="{identifier}">{body}' + ('<tag k="historic" v="castle"/>' if selected else '') + '</relation>'


class RelationCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'fixture.osm'
        self.cache = None

    def tearDown(self):
        if self.cache:
            self.cache.close()
        self.temp.cleanup()

    def read(self, text, limits=None):
        self.source.write_text('<osm version="0.6">'+text+'</osm>')
        self.cache = OsmGeometryCache(self.root/'cache.sqlite', limits)
        self.cache.read(self.source, lambda tags: tags.get('historic') == 'castle')
        return self.cache

    def failure(self, identifier, reason):
        with self.assertRaises(ResolutionError) as caught:
            resolve_relation(self.cache, identifier)
        self.assertEqual(reason, caught.exception.reason)

    def test_self_cycle(self):
        self.read(relation(1,[('relation',1,'')]))
        self.failure(1,'cycle')

    def test_closed_cycle(self):
        self.read(relation(1,[('relation',2,'')])+relation(2,[('relation',1,'')]))
        self.failure(1,'cycle')
        self.failure(2,'cycle')

    def test_shared_child_is_not_a_cycle_and_roles_are_independent(self):
        self.read('<node id="1" lat="40" lon="1"/>'+relation(2,[('node',1,'')])+
                  relation(3,[('relation',2,'left'),('relation',2,'right')]))
        result=resolve_relation(self.cache,3)
        self.assertEqual(['left','right'],[m['role'] for m in result['members']])
        result['members'][0]['members'][0]['lat']=99
        self.assertEqual(40,result['members'][1]['members'][0]['lat'])

    def test_forward_and_out_of_order_dependencies(self):
        self.read(relation(1,[('relation',2,'outer')])+relation(2,[('way',3,'')])+
                  '<way id="3"><nd ref="7"/><nd ref="8"/></way>'+
                  '<node id="8" lat="41" lon="2"/><node id="7" lat="40" lon="1"/>')
        result=resolve_relation(self.cache,1)
        self.assertEqual([40,41],[p['lat'] for p in result['members'][0]['members'][0]['geometry']])

    def test_missing_relation(self):
        self.read(relation(1,[('relation',999,'')]))
        self.failure(1,'missing_relation')

    def test_missing_way_node(self):
        self.read('<way id="1"><nd ref="999"/></way>'+relation(1,[('way',1,'')]))
        self.failure(1,'missing_way_node')

    def test_missing_direct_node(self):
        self.read(relation(1,[('node',999,'')]))
        self.failure(1,'missing_node')

    def test_missing_way(self):
        self.read(relation(1,[('way',999,'')]))
        self.failure(1,'missing_way')

    def test_depth_limit_does_not_poison_shallow_resolution(self):
        self.read('<node id="1" lat="40" lon="1"/>'+relation(1,[('relation',2,'')])+
                  relation(2,[('relation',3,'')])+relation(3,[('node',1,'')]),Limits(max_depth=2))
        self.failure(1,'depth_limit')
        self.assertEqual(2,resolve_relation(self.cache,2)['id'])

    def test_long_chain_terminates_without_python_recursion(self):
        self.read(''.join(relation(i,[('relation',i+1,'')]) for i in range(1,1500)))
        self.failure(1,'depth_limit')

    def test_expansion_budget_handles_branching_dag(self):
        self.read('<node id="1" lat="40" lon="1"/>'+relation(1,[('node',1,'')])+
                  ''.join(relation(i,[('relation',i-1,''),('relation',i-1,'')]) for i in range(2,10)),
                  Limits(max_objects=30))
        self.failure(9,'expansion_limit')
        self.assertEqual(1,resolve_relation(self.cache,1)['id'])

    def test_point_budget_counts_repeated_geometry(self):
        self.read('<node id="1" lat="40" lon="1"/><way id="1"><nd ref="1"/><nd ref="1"/></way>'+
                  relation(1,[('way',1,''),('way',1,'')]),Limits(max_points=3))
        self.failure(1,'expansion_limit')

    def test_oversized_member_list(self):
        self.read(relation(1,[('node',1,''),('node',2,'')]),Limits(max_members=1))
        self.failure(1,'member_limit')

    def test_excluded_roles_keep_existing_policy(self):
        self.read('<node id="1" lat="40" lon="1"/>'+relation(1,[('node',1,'outer'),('relation',1,'approach'),('node',999,'descent')]))
        self.assertEqual(1,len(resolve_relation(self.cache,1)['members']))

    def test_way_geometry_cached_on_disk(self):
        self.read('<node id="1" lat="40" lon="1"/><way id="1"><nd ref="1"/></way>')
        self.cache.way(1)
        # Confirm the second lookup uses persisted geometry, not the dependency table.
        self.cache.db.execute('DELETE FROM nodes')
        self.assertEqual(40,self.cache.way(1)['geometry'][0]['lat'])

    def test_empty_relation_rejected(self):
        self.read(relation(1,[]))
        self.failure(1,'empty_relation')

    def test_requires_completed_import(self):
        self.cache=OsmGeometryCache(self.root/'empty.sqlite')
        with self.assertRaises(ValueError):resolve_relation(self.cache,1)

    def test_duplicate_snapshot_ids_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate OSM IDs'):
            self.read('<node id="1" lat="40" lon="1"/><node id="1" lat="41" lon="2"/>')

    def test_builder_one_reader_and_cycles_mark_partial_coverage(self):
        self.source.write_text('<osm version="0.6">'+relation(1,[('relation',1,'')],True)+'</osm>')
        output=self.root/'pois.sqlite'
        with patch('osmium.io.Reader', wraps=osmium.io.Reader) as reader:
            result=build(self.source,output,CATALOG,coverage={'type':'MultiPolygon','coordinates':[]},
                         package_id='test',name='Test',country='ES')
            self.assertEqual(1,reader.call_count)
        self.assertEqual(1,result['incomplete_relations'])
        with sqlite3.connect(output) as db:
            self.assertEqual('false',db.execute("SELECT value FROM metadata WHERE key='coverage_complete'").fetchone()[0])
            self.assertEqual({'cycle':1},json.loads(db.execute("SELECT value FROM metadata WHERE key='resolution_failures'").fetchone()[0]))
        self.assertFalse(list(self.root.glob('rutasgen-osm-*')))

    def test_pbf_input_is_processed_in_one_pass(self):
        self.source.write_text('<osm version="0.6"><node id="1" lat="40" lon="1"/>'+
                              relation(1,[('node',1,'')],True)+'</osm>')
        pbf=self.root/'fixture.osm.pbf'
        with osmium.SimpleWriter(str(pbf)) as writer:
            for obj in osmium.FileProcessor(str(self.source)):
                if obj.is_node(): writer.add_node(obj)
                elif obj.is_relation(): writer.add_relation(obj)
        with patch('osmium.io.Reader', wraps=osmium.io.Reader) as reader:
            result=build(pbf,self.root/'pbf.sqlite',CATALOG)
            self.assertEqual(1,reader.call_count)
        self.assertEqual(1,result['pois'])
        self.assertEqual(0,result['incomplete_relations'])

    def test_failed_import_preserves_existing_output_and_removes_temporary(self):
        self.source.write_text('<osm broken')
        output=self.root/'pois.sqlite';output.write_bytes(b'existing package')
        with self.assertRaises(Exception):build(self.source,output,CATALOG)
        self.assertEqual(b'existing package',output.read_bytes())
        self.assertFalse(list(self.root.glob('rutasgen-osm-*')))

if __name__=='__main__':unittest.main()
