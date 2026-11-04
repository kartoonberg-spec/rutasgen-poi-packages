import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from build_osm_poi_package import create_schema, insert_element
from offline_package_metadata import attach_metadata
from publish_packages import entry_for

class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'fr-poi.sqlite'
        with sqlite3.connect(self.path) as db:
            create_schema(db, 'fixture.osm')
            attach_metadata(db, selectors=[({'natural': 'peak'}, False)],
                coverage={'type':'MultiPolygon','coordinates':[[[[0,0],[1,0],[1,1],[0,0]]]]},
                package_id='fr-test', name='France test', country='FR', skipped={})
            db.execute('INSERT INTO metadata VALUES (?,?)', ('source_snapshot_utc','2026-01-01T00:00:00Z'))
            insert_element(db, {'type':'node','id':1,'lat':0.5,'lon':0.5,'tags':{'natural':'peak'}})

    def entry(self):
        return entry_for(self.path, 'example/packages', 'poi-1')

    def test_exact_hash_size_and_versioned_url(self):
        result = self.entry()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), result['sha256'])
        self.assertEqual(self.path.stat().st_size, result['bytes'])
        self.assertEqual('https://github.com/example/packages/releases/download/poi-1/fr-poi.sqlite', result['url'])
        self.assertEqual(1, result['count'])

    def test_incomplete_is_never_promoted_to_complete(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE metadata SET value='false' WHERE key='coverage_complete'")
        self.assertFalse(self.entry()['complete'])

    def test_empty_country_rejected(self):
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM pois')
        with self.assertRaises(ValueError): self.entry()

    def test_oversized_package_rejected(self):
        with patch('publish_packages.MAX_PACKAGE', 1):
            with self.assertRaises(ValueError): self.entry()

    def test_missing_snapshot_rejected(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM metadata WHERE key='source_snapshot_utc'")
        with self.assertRaises(KeyError): self.entry()

    def test_invalid_tag_rejected(self):
        with self.assertRaises(ValueError):
            entry_for(self.path, 'example/packages', '../wrong')
