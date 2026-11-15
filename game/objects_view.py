"""오브젝트 상태를 읽어 이미지와 효과를 표시하고 해제한다."""
import json

import pico2d as p

from game.paths import ART_ROOT
from game.vfx.pico import PicoEffect


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


class JumpPadView:
    """발판 상태를 읽어 기본·눌림 아틀라스 이미지를 표시한다."""

    def __init__(self, pad, zoom=.5):
        self.pad, self.zoom = pad, zoom
        self.assets = ART_ROOT / 'environment'
        data = json.loads((self.assets / 'environment.json').read_text(encoding='utf-8'))
        self.frames = {item['id']: item for item in data['assets']
                       if item['id'] in ('spring_rest', 'spring_pressed')}
        self.atlases = data['atlases']
        self.image = None

    @property
    def frame(self):
        return self.frames['spring_pressed' if self.pad.pressed else 'spring_rest']

    def draw(self, offset=(0, 0)):
        frame = self.frame
        if self.image is None:
            self.image = p.load_image(str(self.assets / self.atlases[frame['atlas']]['image']))
        left, top, width, height = frame['rect']
        anchor_x, anchor_y = frame['anchor_px']
        x = self.pad.area.left + self.pad.area.width / 2 - offset[0]
        y = self.pad.area.bottom - offset[1]
        self.image.clip_composite_draw(
            left, self.image.h - top - height, width, height, 0, '',
            x + (width / 2 - anchor_x) * self.zoom,
            y + (anchor_y - height / 2) * self.zoom,
            width * self.zoom, height * self.zoom,
        )

    def close(self):
        self.image = None


class MovingPlatformView:
    """기존 발판의 왼쪽·중앙·오른쪽 모듈을 이동 상자 윗면에 맞춰 표시한다."""

    def __init__(self, platform):
        self.platform = platform
        self.assets = ART_ROOT / 'environment'
        data = json.loads((self.assets / 'environment.json').read_text(encoding='utf-8'))
        frames = {item['id']: item for item in data['assets']}
        self.frames = tuple(frames[name] for name in ('solid-left', 'solid-middle', 'solid-right'))
        self.image_path = self.assets / data['atlases'][self.frames[0]['atlas']]['image']
        self.image = None

    def draw(self, offset=(0, 0)):
        if self.image is None:
            self.image = p.load_image(str(self.image_path))
        area = self.platform.area
        zoom = area.width / sum(frame['rect'][2] for frame in self.frames)
        x, y = area.left - offset[0], area.top - offset[1]
        for frame in self.frames:
            left, top, width, height = frame['rect']
            self.image.clip_composite_draw(
                left, self.image.h - top - height, width, height, 0, '',
                x + width * zoom / 2, y + (frame['surface_y_px'] - height / 2) * zoom,
                width * zoom, height * zoom,
            )
            x += width * zoom

    def close(self):
        self.image = None
