from pathlib import Path
import sqlite3
import tempfile
import unittest
from offline_package_metadata import read_poly,attach_metadata,catalog_signature
from build_osm_poi_package import create_schema,selectors_from_catalog,build
CATALOG=Path(__file__).resolve().parents[1]/'catalog/OsmHikingCatalog.kt'
class MetadataTest(unittest.TestCase):
 def test_boundary_does_not_come_from_poi_extents(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'test.poly'
   path.write_text('test\n1\n 0 0\n 10 0\n 10 10\n 0 10\n 0 0\nEND\n!1\n 4 4\n 6 4\n 6 6\n 4 6\n 4 4\nEND\nEND\n')
   coverage=read_poly(path)
   self.assertEqual(2,len(coverage['coordinates'][0]))
   self.assertEqual([10.0,10.0],coverage['coordinates'][0][0][2])
 def test_empty_area_can_be_complete_but_skipped_geometry_cannot(self):
  for skipped,complete in [({},'true'),({'incomplete_relations':1},'false')]:
   with sqlite3.connect(':memory:') as db:
    create_schema(db,'test')
    attach_metadata(db,selectors=selectors_from_catalog(CATALOG),coverage={'type':'MultiPolygon','coordinates':[]},package_id='test',name='Test',country='ES',skipped=skipped)
    self.assertEqual(0,db.execute('select count(*) from pois').fetchone()[0])
    self.assertEqual(complete,dict(db.execute('select * from metadata'))['coverage_complete'])
 def test_signature_is_order_independent_and_changes_with_catalog(self):
  selectors=[({'natural':'peak'},False),({'natural':'tree'},True)]
  self.assertEqual(catalog_signature(selectors),catalog_signature(selectors[::-1]))
  self.assertNotEqual(catalog_signature(selectors),catalog_signature([({'natural':'tree'},False)]))
 def test_incomplete_boundary_is_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'bad.poly';path.write_text('test\n1\n 0 0\n 1 0\n 1 1\n')
   with self.assertRaises(ValueError): read_poly(path)
if __name__=='__main__': unittest.main()
