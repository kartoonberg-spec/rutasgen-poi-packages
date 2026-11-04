import unittest
from europe_catalog import merge, missing_regions
from publish_packages import REGIONS

def entry(identifier, date='2026-11-03', complete=True):
    return dict(id=identifier, snapshot=date, country='FR', name=identifier,
                bytes=100, sha256='a'*64, complete=complete)

class EuropeCatalogTest(unittest.TestCase):
    def test_previous_countries_are_kept(self):
        result = merge({'packages':[entry('fr-geofabrik'),entry('it-geofabrik')]}, [entry('portugal-geofabrik')])
        self.assertEqual(3,len(result['packages']))
    def test_older_snapshot_does_not_replace_current(self):
        result = merge({'packages':[entry('fr-geofabrik')]}, [entry('fr-geofabrik','2020-01-01')])
        self.assertEqual('2026-11-03',result['packages'][0]['snapshot'])
    def test_partial_status_survives(self):
        result = merge({'packages':[]}, [entry('fr-geofabrik',complete=False)])
        self.assertFalse(result['packages'][0]['complete'])
    def test_existing_packages_not_rebuilt(self):
        missing = missing_regions({'packages':[entry('fr-geofabrik'),entry('it-geofabrik')]})
        self.assertNotIn('fr',missing);self.assertNotIn('it',missing)
        self.assertIn('portugal',missing)
    def test_large_germany_split_and_russia_not_whole(self):
        self.assertNotIn('germany',REGIONS);self.assertNotIn('russia',REGIONS)
        self.assertIn('bayern',REGIONS);self.assertIn('kaliningrad',REGIONS)
    def test_ids_and_country_codes_match_android_contract(self):
        import re
        for key, (extract,name,country) in REGIONS.items():
            self.assertRegex(key+'-geofabrik',r'^[a-zA-Z0-9_-]{1,80}$')
            self.assertRegex(country,r'^[A-Z]{2}$')
            self.assertTrue(name and '..' not in extract)
