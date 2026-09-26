"""Offline Windows OCR. Row count must agree with EMR's displayed total."""
import asyncio
from dataclasses import dataclass
import re
from PIL import ImageOps
from .core import Row, Snapshot, compact


@dataclass(frozen=True)
class Word:
    text: str
    x: float
    y: float
    width: float
    height: float

    @property
    def cy(self):
        return self.y + self.height / 2


class Reader:
    def __init__(self, clean=False):
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        self.engine = OcrEngine.try_create_from_language(Language('ko-KR'))
        self.clean = clean
        if self.engine is None:
            raise ValueError('Windows 한국어 OCR 언어팩이 필요합니다. 설정 → 언어에서 한국어 OCR을 설치하세요.')

    async def _read(self, image):
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
        from winrt.windows.storage.streams import DataWriter
        # Scale small EMR fonts without exceeding the OS engine limit.
        # Clear colored cell backgrounds and pad small labels for Windows OCR.
        padding = 12 if self.clean else 0
        prepared = (ImageOps.expand(ImageOps.grayscale(image).point(lambda value: 0 if value < 155 else 255),
                                   border=padding, fill=255) if self.clean else image)
        scale = min(3.0 if self.clean else 2.0, OcrEngine.max_image_dimension / max(prepared.size))
        scaled = prepared.resize((int(prepared.width * scale), int(prepared.height * scale)))
        writer = DataWriter()
        bitmap = None
        try:
            writer.write_bytes(scaled.convert('RGBA').tobytes('raw', 'BGRA'))
            bitmap = SoftwareBitmap.create_copy_with_alpha_from_buffer(
                writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                scaled.width, scaled.height, BitmapAlphaMode.IGNORE)
            result = await self.engine.recognize_async(bitmap)
            return [Word(word.text, word.bounding_rect.x / scale - padding, word.bounding_rect.y / scale - padding,
                         word.bounding_rect.width / scale, word.bounding_rect.height / scale)
                    for line in result.lines for word in line.words]
        finally:
            if bitmap:
                bitmap.close()
            writer.close()

    def words(self, image):
        return asyncio.run(self._read(image))

    def text(self, image):
        return compact(' '.join(w.text for w in self.words(image)))


def parse_table(words, columns, header_height, expected_count, date, department):
    """Columns are calibrated pixel boundaries relative to the table crop."""
    def cell_words(name):
        left, right = columns[name]
        return [w for w in words if w.y >= header_height and left <= w.x + w.width / 2 < right]

    id_words = sorted(cell_words('등록번호'), key=lambda w: w.cy)
    anchors = []
    for word in id_words:
        # No guessing O/0 or dropping a partially read identifier.
        if not re.fullmatch(r'\d{5,12}', compact(word.text)):
            raise ValueError('등록번호 인식 불확실 — 기준을 변경하지 않습니다.')
        anchors.append(word)
    if len(anchors) != expected_count:
        raise ValueError('총 건수와 보이는 행 수가 다릅니다. 가림·스크롤·OCR 상태를 확인하세요.')
    if expected_count and any(b.cy - a.cy < 10 for a, b in zip(anchors, anchors[1:])):
        raise ValueError('행 간격을 식별할 수 없습니다.')
    rows = []
    for index, anchor in enumerate(anchors):
        lower = (anchors[index - 1].cy + anchor.cy) / 2 if index else header_height
        upper = (anchor.cy + anchors[index + 1].cy) / 2 if index + 1 < len(anchors) else anchor.cy + max(10, anchor.height)
        cells = {}
        for name in columns:
            cell = sorted((w for w in cell_words(name) if lower <= w.cy < upper), key=lambda w: w.x)
            cells[name] = compact(' '.join(w.text for w in cell))
        other = sorted((w for w in words if w.y >= header_height and lower <= w.cy < upper
                        and not any(left <= w.x + w.width / 2 < right for left, right in columns.values())),
                       key=lambda w: w.x)
        cells['세부항목'] = compact(' '.join(w.text for w in other))
        if not cells['환자상태'] or not cells['수술명']:
            raise ValueError('환자상태 또는 수술명 인식 실패 — 알림 판정을 보류합니다.')
        details = tuple(sorted((k, v) for k, v in cells.items() if k not in ('등록번호', '수술명', '환자상태')))
        rows.append(Row(cells['등록번호'], cells['수술명'], cells['환자상태'], details))
    return Snapshot(date, department, tuple(rows))
