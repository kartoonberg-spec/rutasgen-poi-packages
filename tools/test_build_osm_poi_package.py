import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from build_osm_poi_package import build, create_schema, insert_element, selectors_from_catalog, matches

CATALOG = Path(__file__).resolve().parents[1] / 'catalog/OsmHikingCatalog.kt'
if not CATALOG.exists():
    CATALOG = Path(__file__).resolve().parents[2] / 'project/source/kartoonberg-spec-s-org/app/src/main/java/com/example/domain/model/OsmHikingCatalog.kt'

class PackageTest(unittest.TestCase):
    def test_catalog_keeps_automatic_and_excludes_map_only(self):
        selectors = selectors_from_catalog(CATALOG)
        for tags in [{'natural':'peak'}, {'natural':'spring'}, {'amenity':'fountain'},
                     {'man_made':'water_tap','drinking_water':'yes'}, {'bridge':'yes'},
                     {'route':'via_ferrata'}, {'natural':'tree','name':'Roble'}]:
            self.assertTrue(matches(tags, selectors), tags)
        for tags in [{'natural':'wood'}, {'natural':'tree'}, {'waterway':'river'},
                     {'man_made':'water_tap','drinking_water':'no'}]:
            self.assertFalse(matches(tags, selectors), tags)

    def test_real_osm_processing_preserves_ids_geometry_and_relations(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder)/'fixture.osm', Path(folder)/'es-test.sqlite'
            source.write_text('''<osm version="0.6" generator="test">
<node id="1" lat="40.0" lon="0.0"><tag k="amenity" v="drinking_water"/></node>
<node id="2" lat="40.001" lon="0.001"/>
<node id="3" lat="40.002" lon="0.002"><tag k="natural" v="tree"/></node>
<way id="1"><nd ref="1"/><nd ref="2"/><tag k="bridge" v="yes"/></way>
<way id="2"><nd ref="2"/><nd ref="3"/></way>
<relation id="1"><member type="way" ref="1" role=""/><member type="way" ref="2" role="approach"/>
<tag k="route" v="via_ferrata"/></relation></osm>''', encoding='utf-8')
            result = build(source, output, CATALOG)
            self.assertEqual(3, result['pois'])
            with sqlite3.connect(output) as db:
                rows = {key: json.loads(data) for key, data in db.execute('SELECT id,element FROM pois')}
                self.assertEqual({'node/1','way/1','relation/1'}, rows.keys())
                self.assertEqual(2, len(rows['way/1']['geometry']))
                self.assertEqual(1, len(rows['relation/1']['members']))
                self.assertEqual('ok', db.execute('PRAGMA integrity_check').fetchone()[0])
                self.assertEqual('rutasgen-osm-poi-v1', db.execute("SELECT value FROM metadata WHERE key='format'").fetchone()[0])
            self.assertFalse(output.with_suffix('.sqlite.part').exists())

    def test_nested_relation_members_are_resolved_without_losing_the_parent_id(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder)/'nested.osm', Path(folder)/'nested.sqlite'
            source.write_text('''<osm version="0.6"><node id="1" lat="40" lon="0"/><node id="2" lat="40.001" lon="0.001"/>
<way id="1"><nd ref="1"/><nd ref="2"/></way>
<relation id="1"><member type="way" ref="1" role="outer"/><tag k="type" v="multipolygon"/></relation>
<relation id="2"><member type="relation" ref="1" role="outer"/><tag k="historic" v="castle"/></relation></osm>''')
            result=build(source,output,CATALOG)
            self.assertEqual(0,result['incomplete_relations'])
            with sqlite3.connect(output) as db:
                element=json.loads(db.execute("SELECT element FROM pois WHERE id='relation/2'").fetchone()[0])
                self.assertEqual('relation',element['members'][0]['type'])
                self.assertEqual(2,len(element['members'][0]['members'][0]['geometry']))

    def test_invalid_coordinate_is_not_written(self):
        with sqlite3.connect(':memory:') as db:
            create_schema(db,'test')
            for lat in [float('nan'), float('inf'), 91]:
                self.assertFalse(insert_element(db,dict(type='node',id=1,lat=lat,lon=0,tags={})))
            self.assertEqual(0,db.execute('SELECT count(*) FROM pois').fetchone()[0])

if __name__ == '__main__': unittest.main()
