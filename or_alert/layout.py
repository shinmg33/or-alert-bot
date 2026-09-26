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


# Widths distinguish the surgery list from other blue tables without reading PII.
PROFILE = [34,70,73,50,50,50,78,78,71,75,70,50,130,40,130,50,25,60,70,67,70,59,27]


def detect_grid(image, words=None):
    image = image.convert('RGB')
    pixels = image.load()
    candidates = []
    for y in range(image.height):
        color, count = Counter(pixels[x, y] for x in range(0, image.width, 4)).most_common(1)[0]
        r, g, b = color
        if count * 4 > image.width * .40 and 80 <= r <= 190 and g > r + 20 and b > g:
            candidates.append((y, color))
    matches = set()
    for top, color in candidates:
        for bottom, other in candidates:
            if other != color or not 12 <= bottom-top <= 70:
                continue
            scale = (bottom-top)/23
            lines = runs([x for x in range(image.width) if all(
                max(abs(a-b) for a,b in zip(pixels[x,y],color)) <= 8
                for y in (top+2,bottom-2))])
            groups = [[]]
            for x in lines:
                if groups[-1] and x-groups[-1][-1] > 250*scale:
                    groups.append([])
                groups[-1].append(x)
            for group in groups:
                if len(group) != 24:
                    continue
                widths = [b-a for a,b in zip(group,group[1:])]
                if all(abs(actual-expected*scale) <= max(4*scale, expected*scale*.18)
                       for actual,expected in zip(widths,PROFILE)):
                    matches.add((tuple(group),top,bottom))
    if len(matches) != 1:
        raise LayoutError('수술 표의 격자 배치를 확인하지 못했습니다. 이 화면의 표 배치에 맞는 인식 보정이 필요합니다.')
    lines,top,bottom = matches.pop()
    return list(lines),top,bottom


def auto_layout(image, reader, overrides=None):
    overrides = overrides or {}
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
        kind = 'department' if expected == '진료과' else 'doctor'
        if kind in overrides:
            continue
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
    if 'query' not in overrides:
        query = [w for w in words if compact(w.text) == '조회' and w.y < top
                 and abs(w.cy - (rects['department'][1]+rects['department'][3])/2) < 15*scale]
        if len(query) != 1:
            raise LayoutError('조회 버튼을 자동으로 찾지 못했습니다. 위치 보정에서 조회 버튼을 지정하세요.')
        q = query[0]
        rects['query'] = [max(0,int(q.x-4*scale)),max(0,int(q.y-3*scale)),
                          min(image.width,int(q.x+q.width+4*scale)),min(image.height,int(q.y+q.height+3*scale))]
    for name, area in overrides.items():
        if name in ('department','doctor','query'):
            if len(area) != 4 or not (0 <= area[0] < area[2] <= image.width and 0 <= area[1] < area[3] < top):
                raise LayoutError('위치 보정은 표 위의 진료과·진료의·조회 영역만 지정할 수 있습니다.')
            rects[name] = list(area)
    columns = {name: [lines[index]-lines[0]+1, lines[index+1]-lines[0]]
               for name, index in [('등록번호', 9), ('수술명', 12), ('환자상태', 19)]}
    return {'size': list(image.size), 'rects': rects, 'columns': columns,
            'header_height': bottom-top+1, 'auto_layout': True, 'layout_version': 3}
