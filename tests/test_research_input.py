from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
import zipfile
from research.repo_baseline import common_segment,load_asset

class ResearchInputTests(unittest.TestCase):
    def test_mixed_folder_selects_only_requested_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            for asset,price in [('BTC',100),('ETH',20),('HYPE',3)]:
                with zipfile.ZipFile(Path(folder)/f'2026-10-02_{asset}.csv.zip','w') as z:
                    z.writestr('prices.csv',f'timestamp_utc,price_usd,source\n2026-10-02T00:00:00Z,{price},test\n')
            prices,manifest=load_asset(Path(folder),'BTC')
            self.assertEqual(list(prices.values()),[100])
            self.assertEqual(len(manifest['files']),1)
            self.assertEqual(manifest['rows'],1)
            with self.assertRaisesRegex(ValueError,'Unsupported'):
                load_asset(Path(folder),'SOL')

    def test_common_segment_respects_gaps_and_cutoff(self):
        start=datetime(2026,10,2,tzinfo=timezone.utc)
        prices={start+timedelta(minutes=i):100 for i in range(900)}
        other=dict(prices)
        del other[start+timedelta(minutes=400)]
        result=common_segment({'BTC':prices,'ETH':other},start+timedelta(minutes=800))
        self.assertEqual(min(result['BTC']),start)
        self.assertEqual(max(result['BTC']),start+timedelta(minutes=399))
        self.assertEqual(set(result['BTC']),set(result['ETH']))
        with self.assertRaisesRegex(ValueError,'too short'):
            common_segment({'BTC':prices},start+timedelta(minutes=100))
