"""오브젝트 상태를 읽어 이미지와 효과를 표시하고 해제한다."""
import json
from functools import lru_cache

import pico2d as p

from game.core.collision import AABB
from game.core.paths import ART_ROOT
from game.core.rendering import draw_clip
from game.vfx.electric import ElectricEffect


class ElectricView:
    """Appearance of an Electric object; collision remains in the model."""
    def __init__(self, electric):
        self.electric = electric
        self.effect = ElectricEffect(electric.bands)

    def prerender(self):
        self.effect.prerender()

    def reset(self):
        self.effect.reset()

    def update(self, dt):
        self.effect.update(dt)

    def draw(self, camera):
        self.effect.draw(camera)

    def close(self):
        self.effect.close()


@lru_cache(maxsize=1)
def environment_data():
    return json.loads((ART_ROOT / 'environment/environment.json').read_text(encoding='utf-8'))


def draw_visual(visual, images, offset=(0, 0), *, shift=(0, 0), source=None, frame=None, reference=None):
    """Draw a world-space visual rectangle; state changes preserve its anchor."""
    path = visual['image']
    if path not in images:
        images[path] = p.load_image(path)
    image = images[path]
    x, y, w, h = visual['rect']
    clip = visual['source'] if source is None else source
    if frame is not None and reference is not None:
        sx, sy = w / reference['rect'][2], h / reference['rect'][3]
        x += (reference['anchor_px'][0] - frame['anchor_px'][0])*sx
        y += (reference['rect'][3] - reference['anchor_px'][1]
              + frame['anchor_px'][1] - frame['rect'][3])*sy
        w, h = frame['rect'][2]*sx, frame['rect'][3]*sy
        clip = frame['rect']
    left, top, width, height = clip
    draw_clip(image, left, image.h-top-height, width, height, 0, '',
              x+w/2-offset[0]+shift[0], y+h/2-offset[1]+shift[1], w, h)


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

    vanish_time = .3
    idle_frames = 24
    idle_fps = 20
    visual_scale = 40 / 28

    def __init__(self, source, image=None):
        self.source = source
        self.image = image
        self.reset()

    def reset(self):
        self._consumed = self.source.consumed
        self.vanish_left = 0.0
        self.idle_age = 0.0

    def update(self, dt):
        if self.source.consumed != self._consumed:
            self._consumed = self.source.consumed
            self.vanish_left = self.vanish_time if self._consumed else 0.0
        self.vanish_left = max(0.0, self.vanish_left - dt)
        if not self._consumed:
            self.idle_age = (self.idle_age + dt) % (self.idle_frames / self.idle_fps)

    @property
    def draw_area(self):
        area = self.source.area
        width, height = area.width * self.visual_scale, area.height * self.visual_scale
        return AABB(area.left + (area.width - width) / 2, area.bottom + (area.height - height) / 2,
                    width, height)

    def draw(self, offset=(0, 0)):
        if self.source.consumed:
            if self.vanish_left <= 0:
                return
            frame = min(5, int((1 - self.vanish_left / self.vanish_time) * 6))
            bottom = 0
        else:
            frame = min(self.idle_frames - 1, int(self.idle_age * self.idle_fps))
            bottom = 64
        if self.image is None:
            self.image = p.load_image(str(ART_ROOT / 'environment/objects/dash-orb-fx.png'))
        area = self.draw_area
        x = area.left + area.width / 2 - offset[0]
        y = area.bottom + area.height / 2 - offset[1]
        draw_clip(self.image, frame * 64, bottom, 64, 64, 0, '', x, y, area.width, area.height)

    def close(self):
        self.image = None


class JumpPlatformView:
    """발판 상태를 읽어 기본·눌림 아틀라스 이미지를 표시한다."""

    def __init__(self, platform, zoom=.5, *, visual=None, images=None):
        self.platform = platform
        self.visual = visual
        self.images = images if images is not None else {}
        self.assets = ART_ROOT / 'environment'
        data = environment_data()
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
        if self.visual is not None:
            draw_visual(self.visual, self.images, offset, frame=frame, reference=self.frames['spring_rest'])
            return
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

    def __init__(self, area, *, one_way=False, visual=None, images=None):
        self.area = area
        self.visual = visual
        self.images = images if images is not None else {}
        self.assets = ART_ROOT / 'environment'
        data = environment_data()
        frames = {item['id']: item for item in data['assets']}
        prefix = 'pass_through' if one_way else 'solid'
        self.frames = tuple(frames[prefix + '-' + part] for part in ('left', 'middle', 'right'))
        self.image_path = self.assets / data['atlases'][self.frames[0]['atlas']]['image']
        self.image = None

    def draw(self, offset=(0, 0)):
        if self.visual is not None:
            draw_visual(self.visual, self.images, offset)
            return
        if self.image is None:
            self.image = p.load_image(str(self.image_path))
        _draw_platform(self.image, self.frames, self.area, offset)

    def close(self):
        self.image = None


class MovingPlatformView:
    """롤러와 방향 화살표가 있는 컨베이어 원본을 수평 이동 발판으로 사용한다."""

    def __init__(self, platform, *, visual=None, images=None):
        self.platform = platform
        self.visual = visual
        self.images = images if images is not None else {}
        self.assets = ART_ROOT / 'environment'
        data = environment_data()
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
        if self.visual is not None:
            draw_visual(self.visual, self.images, offset,
                        shift=(self.platform.area.left-self.platform.start_area.left, 0),
                        source=self.frames[0]['rect'])
            return
        if self.image is None:
            self.image = p.load_image(str(self.image_path))
        _draw_platform(self.image, self.frames, self.platform.area, offset)

    def close(self):
        self.image = None


class DisappearingPlatformView:
    """기본·경고 이미지를 선택하며 소멸 중에는 그리지 않는다."""

    def __init__(self, platform, *, visual=None, images=None):
        self.platform = platform
        self.visual = visual
        self.images = images if images is not None else {}
        self.assets = ART_ROOT / 'environment'
        data = environment_data()
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
        if self.visual is not None:
            x, y, w, h = self.visual['source']
            row_shift = self.frames[0]['rect'][1] - self.frame_sets['READY'][0]['rect'][1]
            source = [x, y + row_shift, w, h]
            draw_visual(self.visual, self.images, offset, source=source)
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
