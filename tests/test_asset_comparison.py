import csv
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from research.compare_assets import read_archive
from research.reversal_study import minute_prices
from hedger.sim_input import Observation
from decimal import Decimal


class BinanceConversionTests(unittest.TestCase):
    def archive(self, root, bad_duration=False):
        path=Path(root)/'candles.zip'
        stream=io.StringIO()
        w=csv.writer(stream)
        w.writerow(['open_time','close_time','low','high','close'])
        base=int(datetime(2026,10,2,tzinfo=timezone.utc).timestamp()*1000)
        for i in range(1440):
            t=base+i*60000
            w.writerow([t,t+59999+(1 if bad_duration and i==0 else 0),99,101,100])
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('candles.csv',stream.getvalue())
        path.with_suffix('.zip.CHECKSUM').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+' candles.zip')
        return path

    def test_close_is_available_at_minute_end_not_open(self):
        with tempfile.TemporaryDirectory() as root:
            rows,_=read_archive(self.archive(root),'2026-10-02')
            self.assertEqual(rows[0][0],'2026-10-02T00:00:59.999000Z')
            self.assertEqual(rows[-1][0],'2026-10-02T23:59:59.999000Z')
            observations=[Observation(datetime.fromisoformat(t.replace('Z','+00:00')),Decimal(p),'test') for t,p in rows]
            prices=minute_prices(observations)
            self.assertEqual(min(prices).isoformat(),'2026-10-02T00:01:00+00:00')
            self.assertEqual(max(prices).isoformat(),'2026-10-03T00:00:00+00:00')

    def test_corrupted_archive_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path=self.archive(root)
            with path.open('ab') as f:
                f.write(b'corrupt')
            with self.assertRaisesRegex(ValueError,'Checksum mismatch'):
                read_archive(path,'2026-10-02')

    def test_wrong_candle_duration_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'Unexpected candle duration'):
                read_archive(self.archive(root,True),'2026-10-02')

if __name__=='__main__':
    unittest.main()
