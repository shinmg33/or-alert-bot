import unittest
from PIL import Image, ImageDraw
from or_alert.core import compare
from or_alert.ocr import Word
from or_alert.layout import auto_layout, LayoutError
from or_alert.visual import visual_snapshot


class VisualRowsTest(unittest.TestCase):
    columns = {'등록번호':[1,70], '수술명':[71,150], '환자상태':[151,230]}

    def image(self, rows, color='white'):
        image = Image.new('RGB', (330, 180), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((0,0,329,23), fill=(200,235,246))
        draw.line((0,23,329,23), fill=(146,188,202))
        for i, (pid, state, time) in enumerate(rows):
            top = 23+i*24
            draw.rectangle((0,top+1,329,top+23), fill=color)
            for x, text in [(6,pid),(76,'Operation'),(156,state),(245,time)]:
                draw.text((x,top+5),text, fill='black')
            draw.line((0,top+24,329,top+24), fill=(196,203,204))
        return image

    def snap(self, rows, color='white'):
        return visual_snapshot(self.image(rows,color),self.columns,24,len(rows),'selected','dept')

    def test_visible_status_vs_detail(self):
        base = self.snap([('12345678','A','12:00')])
        self.assertEqual(compare(base,self.snap([('12345678','B','12:00')]))[0].level,'주요')
        self.assertEqual(compare(base,self.snap([('12345678','A','13:00')]))[0].level,'세부')

    def test_new_removed_and_reordered_rows(self):
        a,b = ('12345678','A','12:00'),('87654321','B','14:00')
        self.assertEqual(compare(self.snap([a,b]),self.snap([b,a])),[])
        self.assertIn('신규 행',compare(self.snap([a]),self.snap([a,b]))[0].message)
        self.assertIn('사라진',compare(self.snap([a,b]),self.snap([a]))[0].message)

    def test_background_color_alone_does_not_alert(self):
        rows=[('12345678','A','12:00')]
        self.assertEqual(compare(self.snap(rows),self.snap(rows,(153,204,255))),[])

    def test_partial_capture_fails(self):
        with self.assertRaises(ValueError):
            visual_snapshot(self.image([('12345678','A','12:00')]),self.columns,24,2,'selected','dept')


class AutoLayoutTest(unittest.TestCase):
    def fixture(self, dx=0, dy=0):
        image=Image.new('RGB',(1920+dx,700+dy),'white')
        draw=ImageDraw.Draw(image)
        xs=[11,45,115,188,238,288,338,416,494,565,640,710,760,890,930,1060,1110,1135,1195,1265,1332,1402,1461,1488]
        draw.rectangle((11+dx,206+dy,1488+dx,229+dy),fill=(205,235,245),outline=(146,188,202))
        for x in xs:
            draw.line((x+dx,206+dy,x+dx,229+dy),fill=(146,188,202))
        words=[Word('환자상태',1276+dx,212+dy,46,12), Word('진료과',440+dx,100+dy,36,12),
               Word('진료의',711+dx,100+dy,36,12), Word('조회',1863+dx,100+dy,22,12)]
        class FakeReader:
            def __init__(self): self.headers=iter(['등록번호','환자상태'])
            def words(self,_): return words
            def text(self,_): return next(self.headers)
        return image,FakeReader()

    def test_no_manual_cells_needed(self):
        image,reader=self.fixture()
        result=auto_layout(image,reader)
        self.assertTrue(result['auto_layout'])
        self.assertEqual(result['columns']['등록번호'],[555,629])
        self.assertEqual(result['rects']['department'],[487,97,654,116])

    def test_window_origin_translation(self):
        image,reader=self.fixture(17,9)
        result=auto_layout(image,reader)
        self.assertEqual(result['rects']['department'],[504,106,671,125])

    def test_unknown_layout_does_not_guess(self):
        image,reader=self.fixture()
        ImageDraw.Draw(image).rectangle((565,206,565,229),fill='white')
        with self.assertRaises(LayoutError):
            auto_layout(image,reader)
