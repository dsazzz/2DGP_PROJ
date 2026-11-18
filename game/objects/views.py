"""오브젝트 상태를 읽어 이미지와 효과를 표시하고 해제한다."""
import json

import pico2d as p

from game.paths import ART_ROOT
from game.rendering import draw_clip
from game.vfx.pico import PicoEffect


def _draw_platform(image, frames, area, offset):
    zoom = area.width / sum(frame['rect'][2] for frame in frames)
    x, y = area.left - offset[0], area.top - offset[1]
    for frame in frames:
        left, top, width, height = frame['rect']
        draw_clip(image,
            left, image.h - top - height, width, height, 0, '',
            x + width * zoom / 2, y + (frame['surface_y_px'] - height / 2) * zoom,
            width * zoom, height * zoom,
        )
        x += width * zoom


class AbsorbSourceView:
    """효과의 생성·갱신·출력·정리만 소유한다. 판정과 보상은 변경하지 않는다."""

    def __init__(self, source):
        self.source = source
        self.effect = None
        self.reset()

    def reset(self):
        self.close()
        self._consumed = self.source.consumed
        if not self._consumed:
            self.effect = PicoEffect('source')
            self.effect.prerender_loop()

    def update(self, dt):
        if not self.source.consumed and self._consumed:
            self.reset()
        elif self.source.consumed and not self._consumed:
            phase = self.effect.effect.time if self.effect is not None else 0
            self.close()
            self.effect = PicoEffect('lightAbsorb', idle_phase=phase)
            self._consumed = True
        if self.effect is not None:
            self.effect.update(dt)
            if self.effect.done():
                self.close()

    def draw(self, offset=(0, 0)):
        if self.effect is not None:
            area = self.source.area
            x = area.left + area.width / 2 - offset[0]
            y = area.bottom + area.height / 2 - offset[1]
            self.effect.draw(x, y, scale=1, layer='front')

    def close(self):
        if self.effect is not None:
            self.effect.close()
            self.effect = None


class SpikesView:
    """가시 끝의 이미지 영역과 모델의 위험 영역을 같은 위치에 맞춘다."""

    def __init__(self, spikes):
        self.spikes = spikes
        self.assets = ART_ROOT / 'environment'
        data = json.loads((self.assets / 'environment.json').read_text(encoding='utf-8'))
        self.frame = next(item for item in data['assets'] if item['id'] == 'spikes_up')
        self.image_path = self.assets / data['atlases'][self.frame['atlas']]['image']
        self.image = None

    def draw(self, offset=(0, 0)):
        if self.image is None:
            self.image = p.load_image(str(self.image_path))
        left, top, width, height = self.frame['rect']
        danger_x, danger_y, danger_w, danger_h = self.frame['hazard_rect_px']
        flip = ''
        if self.spikes.ceiling:
            danger_x = width - danger_x - danger_w
            danger_y = height - danger_y - danger_h
            flip = 'hv'
        area = self.spikes.area
        scale_x, scale_y = area.width / danger_w, area.height / danger_h
        draw_clip(self.image,
            left, self.image.h - top - height, width, height, 0, flip,
            area.left - offset[0] + (width / 2 - danger_x) * scale_x,
            area.top - offset[1] + (danger_y - height / 2) * scale_y,
            width * scale_x, height * scale_y,
        )

    def close(self):
        self.image = None


class JumpPlatformView:
    """발판 상태를 읽어 기본·눌림 아틀라스 이미지를 표시한다."""

    def __init__(self, platform, zoom=.5):
        self.platform = platform
        self.assets = ART_ROOT / 'environment'
        data = json.loads((self.assets / 'environment.json').read_text(encoding='utf-8'))
        self.frames = {item['id']: item for item in data['assets']
                       if item['id'] in ('spring_rest', 'spring_pressed')}
        self.atlases = data['atlases']
        self.zoom = zoom / self.atlases[self.frame['atlas']].get('pixel_scale', 1)
        self.image = None

    @property
    def frame(self):
        return self.frames['spring_pressed' if self.platform.pressed else 'spring_rest']

    def draw(self, offset=(0, 0)):
        frame = self.frame
        if self.image is None:
            self.image = p.load_image(str(self.assets / self.atlases[frame['atlas']]['image']))
        left, top, width, height = frame['rect']
        anchor_x, anchor_y = frame['anchor_px']
        x = self.platform.area.left + self.platform.area.width / 2 - offset[0]
        y = self.platform.area.bottom - offset[1]
        draw_clip(self.image,
            left, self.image.h - top - height, width, height, 0, '',
            x + (width / 2 - anchor_x) * self.zoom,
            y + (anchor_y - height / 2) * self.zoom,
            width * self.zoom, height * self.zoom,
        )

    def close(self):
        self.image = None


class PlatformView:
    """일반 철판과 한 종류의 얇은 통과 발판을 표시한다."""

    def __init__(self, area, *, one_way=False):
        self.area = area
        self.assets = ART_ROOT / 'environment'
        data = json.loads((self.assets / 'environment.json').read_text(encoding='utf-8'))
        frames = {item['id']: item for item in data['assets']}
        prefix = 'pass_through' if one_way else 'solid'
        self.frames = tuple(frames[prefix + '-' + part] for part in ('left', 'middle', 'right'))
        self.image_path = self.assets / data['atlases'][self.frames[0]['atlas']]['image']
        self.image = None

    def draw(self, offset=(0, 0)):
        if self.image is None:
            self.image = p.load_image(str(self.image_path))
        _draw_platform(self.image, self.frames, self.area, offset)

    def close(self):
        self.image = None


class MovingPlatformView:
    """롤러와 방향 화살표가 있는 컨베이어 원본을 수평 이동 발판으로 사용한다."""

    def __init__(self, platform):
        self.platform = platform
        self.assets = ART_ROOT / 'environment'
        data = json.loads((self.assets / 'environment.json').read_text(encoding='utf-8'))
        frames = {item['id']: item for item in data['assets']}
        self.directions = {direction: frames['moving_platform_' + direction]
                           for direction in ('left', 'right')}
        self.image_path = self.assets / data['atlases'][self.directions['right']['atlas']]['image']
        self.image = None

    @property
    def frames(self):
        dx = self.platform.delta[0] or self.platform.end_x - self.platform.start_area.left
        return (self.directions['left' if dx < 0 else 'right'],)

    def draw(self, offset=(0, 0)):
        if self.image is None:
            self.image = p.load_image(str(self.image_path))
        _draw_platform(self.image, self.frames, self.platform.area, offset)

    def close(self):
        self.image = None


class DisappearingPlatformView:
    """기본·경고 이미지를 선택하며 소멸 중에는 그리지 않는다."""

    def __init__(self, platform):
        self.platform = platform
        self.assets = ART_ROOT / 'environment'
        data = json.loads((self.assets / 'environment.json').read_text(encoding='utf-8'))
        frames = {item['id']: item for item in data['assets']}
        self.frame_sets = {
            state: tuple(frames[prefix + '-' + part] for part in ('left', 'middle', 'right'))
            for state, prefix in (('READY', 'disappear_normal'), ('WARNING', 'disappear_warning'))
        }
        first = self.frame_sets['READY'][0]
        self.image_path = self.assets / data['atlases'][first['atlas']]['image']
        self.image = None

    @property
    def frames(self):
        return self.frame_sets.get(self.platform.state, ())

    def draw(self, offset=(0, 0)):
        if not self.frames:
            return
        if self.image is None:
            self.image = p.load_image(str(self.image_path))
        warning = self.platform.state == 'WARNING'
        age = self.platform.warning_time - self.platform.time_left
        self.image.opacify(.35 if warning and int(age * 10) % 2 else 1)
        try:
            _draw_platform(self.image, self.frames, self.platform.area, offset)
        finally:
            self.image.opacify(1)

    def close(self):
        self.image = None
