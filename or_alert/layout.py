"""Automatic recognition of the supplied XPLATFORM surgery-list layout.

Profile coordinates are translated/scaled from detected grid lines, then
confirmed with label OCR. Unknown layouts fail before any input is sent.
No patient images or identifiers are embedded in this module.
"""
from collections import Counter
from .core import compact


class LayoutError(ValueError):
    pass


def runs(values):
    grouped = []
    for value in values:
        if not grouped or value > grouped[-1][-1] + 1:
            grouped.append([value])
        else:
            grouped[-1].append(value)
    return [round(sum(group) / len(group)) for group in grouped]


def detect_grid(image, words):
    image = image.convert('RGB')
    anchors = [w for w in words if compact(w.text) == '환자상태']
    if len(anchors) != 1:
        raise LayoutError('수술 목록의 환자상태 머리글을 찾지 못했습니다. 수술 목록 전체가 보이게 해주세요.')
    anchor = anchors[0]
    end = min(image.width, int(anchor.x + anchor.width))
    pixels = image.load()
    candidates = []
    for y in range(max(0, int(anchor.y - anchor.height)), min(image.height, int(anchor.y + anchor.height * 2.5))):
        counts = Counter(pixels[x, y] for x in range(0, end, 2))
        color, count = counts.most_common(1)[0]
        r, g, b = color
        if count > end * .30 and 80 <= r <= 190 and g > r + 20 and b > g:
            candidates.append((y, color))
    if len(candidates) < 2:
        raise LayoutError('수술 표의 격자선을 찾지 못했습니다. 화면 배율과 테마를 확인하세요.')
    top, color = candidates[0]
    bottom = next((y for y, c in reversed(candidates) if c == color and y > anchor.cy), None)
    if bottom is None or not 12 <= bottom - top <= 70:
        raise LayoutError('수술 표의 머리글 경계를 확인하지 못했습니다.')
    lines = runs([x for x in range(image.width) if all(
        max(abs(a-b) for a, b in zip(pixels[x, y], color)) <= 8
        for y in (top + 2, bottom - 2))])
    groups = [[]]
    for x in lines:
        if groups[-1] and x - groups[-1][-1] > 250 * (bottom-top) / 23:
            groups.append([])
        groups[-1].append(x)
    groups = [group for group in groups if group and group[0] < anchor.x < group[-1]]
    lines = groups[0] if len(groups) == 1 else []
    if len(lines) != 24:
        raise LayoutError('현재 표 구성이 제공된 수술 목록과 다릅니다. 열을 지정할 필요는 없으며, 이 화면에 맞는 인식 보정이 필요합니다.')
    return lines, top, bottom


def auto_layout(image, reader, overrides=None):
    words = reader.words(image)
    lines, top, bottom = detect_grid(image, words)
    scale = (bottom - top) / 23
    origin_x = lines[0]
    def box(reference):
        x1, y1, x2, y2 = reference
        result = [round(origin_x + (x1-11)*scale), round(top + (y1-206)*scale),
                  round(origin_x + (x2-11)*scale), round(top + (y2-206)*scale)]
        if not (0 <= result[0] < result[2] <= image.width and 0 <= result[1] < result[3] <= image.height):
            raise LayoutError('EMR 화면 배치를 확인하지 못했습니다. 수술 목록 창을 충분히 크게 열어주세요.')
        return result

    # Structural verification; coordinates are never used for input unverified.
    for expected, area in [('진료과', (437, 97, 479, 116)),
                           ('진료의', (708, 97, 750, 116))]:
        left, upper, right, lower = box(area)
        text = compact(''.join(w.text for w in sorted(words, key=lambda w:w.x)
                              if left <= w.x+w.width/2 <= right and upper <= w.cy <= lower))
        if text != expected:
            raise LayoutError(f'{expected} 위치를 자동 확인하지 못했습니다. 수술 목록 화면을 다시 확인하세요.')

    rects = {
        'department': box((487, 97, 654, 116)),
        'doctor': box((771, 97, 867, 116)),
        'date': box((249, 97, 329, 116)),
        'total': box((79, 97, 118, 116)),
        'status_filter': box((114, 121, 393, 141)),
        'room_filter': box((487, 121, 654, 140)),
        'table': [lines[0], top, lines[-1]+1, image.height],
    }
    query = [w for w in words if compact(w.text) == '조회' and w.y < top
             and abs(w.cy - (rects['department'][1]+rects['department'][3])/2) < 15*scale]
    if len(query) != 1:
        raise LayoutError('조회 버튼을 자동으로 찾지 못했습니다.')
    q = query[0]
    rects['query'] = [max(0, int(q.x-4*scale)), max(0, int(q.y-3*scale)),
                      min(image.width, int(q.x+q.width+4*scale)), min(image.height, int(q.y+q.height+3*scale))]
    for name, area in (overrides or {}).items():
        if name in ('department', 'doctor', 'query'):
            rects[name] = area
    columns = {name: [lines[index]-lines[0]+1, lines[index+1]-lines[0]]
               for name, index in [('등록번호', 9), ('수술명', 12), ('환자상태', 19)]}
    for name, (left, right) in columns.items():
        if name == '수술명':
            continue  # Position validated by the 23-column grid and two unique headers.
        header = image.crop((left+lines[0], top+1, right+lines[0], bottom))
        text = reader.text(header)
        allowed = {'등록번호': {'등록번호', '등록변호'}, '수술명': {'수술명', '수촐명'}, '환자상태': {'환자상태'}}[name]
        if text not in allowed:
            raise LayoutError(f'{name} 머리글을 자동 확인하지 못했습니다. 화면을 선명하게 표시해주세요.')
    return {'size': list(image.size), 'rects': rects, 'columns': columns,
            'header_height': bottom-top+1, 'auto_layout': True, 'layout_version': 2}
