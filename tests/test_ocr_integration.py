import concurrent.futures
import os
import unittest
from PIL import Image, ImageDraw, ImageFont
from or_alert.ocr import Reader


class OfflineOcrTest(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows OCR only')
    def test_korean_ocr_on_worker_thread(self):
        def run():
            image = Image.new('RGB', (500, 80), 'white')
            font = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 24)
            ImageDraw.Draw(image).text((5, 5), '환자상태 수술중 퇴실', font=font, fill='black')
            return Reader().text(image)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(run).result(timeout=20), '환자상태수술중퇴실')


if __name__ == '__main__':
    unittest.main()
