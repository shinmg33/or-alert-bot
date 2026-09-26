"""Compare row glyphs locally; OCR uncertainty never invents clinical status."""
import hashlib
from PIL import ImageOps
from .core import Row, Snapshot


def glyphs(image):
    gray = ImageOps.grayscale(image)
    histogram = gray.histogram()
    background = max(range(256), key=lambda value: histogram[value])
    foreground = gray.getextrema()[0]
    # Normalize antialiased text relative to its row background. A blue/yellow
    # status fill must not turn the same patient ID into a new row identity.
    threshold = (background + foreground) / 2
    return gray.point(lambda v: 0 if v < threshold else 255).convert('1')


def digest(image):
    return hashlib.sha256(glyphs(image).tobytes()).hexdigest()


def row_boundaries(image, header_height):
    pixels = image.convert('RGB').load()
    result = [header_height-1]
    # XPLATFORM row separators are neutral gray, unlike blue/yellow state fills.
    for y in range(header_height, image.height):
        hits = 0
        samples = range(3, image.width-3, 5)
        count = len(samples)
        for x in samples:
            r, g, b = pixels[x, y]
            hits += 160 <= r <= 225 and max(r,g,b)-min(r,g,b) < 32
        if count and hits / count > .85:
            if y-result[-1] > 4:
                result.append(y)
    return result


def visual_snapshot(image, columns, header_height, expected_count, date, department):
    lines = row_boundaries(image, header_height)
    if len(lines)-1 != expected_count:
        raise ValueError('총 건수와 화면의 행 수가 다릅니다. 전체 목록이 보이는지 확인하세요.')
    rows = []
    for top, bottom in zip(lines, lines[1:]):
        if not 12 <= bottom-top <= 80:
            raise ValueError('표 행 경계를 확인하지 못했습니다. 감시를 중단합니다.')
        def cell(name):
            left, right = columns[name]
            return image.crop((left+2, top+2, right-2, bottom-2))
        identifier, operation = cell('등록번호'), cell('수술명')
        if glyphs(identifier).getextrema() == (255,255) or glyphs(operation).getextrema() == (255,255):
            raise ValueError('등록번호 또는 수술명이 빈 화면입니다. 조회 완료 후 다시 시작하세요.')
        detail = glyphs(image.crop((2, top+2, image.width-2, bottom-2)))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(detail)
        for left, right in columns.values():
            draw.rectangle((left-2, 0, right-2, detail.height), fill='white')
        rows.append(Row(digest(identifier), digest(operation), '화면:'+digest(cell('환자상태')),
                        (('세부항목', digest(detail)),)))
    return Snapshot(date, department, tuple(rows))
