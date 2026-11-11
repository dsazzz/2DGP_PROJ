"""플레이어의 기존 애니메이션과 시각 효과. 이동과 행동은 이후 연결."""
import json
import math

import pico2d as p

from game.paths import ART_ROOT
from game.vfx.sparkles import Sparkles
from game.vfx.motion import MotionEchoes
from game.vfx.pico import PicoEffect, load_rgba


class Animation:
    def __init__(self, data):
        self.data = data
        self.select('idle')

    @property
    def clip(self):
        return self.data['clips'][self.name]

    @property
    def frame(self):
        return self.data['frames'][self.clip['frames'][self.index]]

    def select(self, name):
        self.name, self.index, self.elapsed = name, 0, 0.0

    def update(self, dt):
        self.elapsed += dt * 1000
        durations = self.clip['duration_ms']
        while self.elapsed >= durations[self.index]:
            self.elapsed -= durations[self.index]
            if self.index + 1 < len(durations):
                self.index += 1
            elif self.clip['loop']:
                self.index = 0
            else:
                self.elapsed = 0.0
                break


class Player:
    """발 기준 위치에 표시한다. 현재 update는 표현 시간만 갱신한다."""

    def __init__(self, x=320, y=128, zoom=0.5):
        self.assets = ART_ROOT / 'player'
        self.data = json.loads((self.assets / 'player.json').read_text(encoding='utf-8-sig'))
        self.glow = json.loads((self.assets / 'player-glow.json').read_text(encoding='utf-8'))
        self.animation = Animation(self.data)
        self.x, self.y, self.zoom = x, y, zoom
        self.flip = False
        self.appearance = self.glow['active_preset'] + 1
        self.elapsed = 0.0
        self.image = None
        self.glow_images = {}
        self.sparkles = None
        self.grounded = True
        self.clip_elapsed = 0.0
        self.trail = None
        self.echoes = None
        self.samples = []
        self.effect_angle = 0.0

    def play(self, name):
        self.animation.select(name)
        self.clip_elapsed = 0.0
        self.samples.clear()
        if self.trail is not None:
            self.trail.close()
        self.trail = None
        self.effect_angle = {
            'dash_up_right': math.pi / 4, 'dash_down_right': -math.pi / 4,
            'dash_up': math.pi / 2, 'dash_down': -math.pi / 2,
        }.get(name, 0.0)
        if name == 'run' or name.startswith('dash_'):
            effect = 'speedTrail' if name == 'run' else 'dashTrail'
            self.trail = PicoEffect(effect, stage=self.appearance, grounded=self.grounded)

    def set_appearance(self, stage):
        self.appearance = stage

    def update(self, dt):
        self.elapsed += dt
        self.clip_elapsed += dt
        self.animation.update(dt)
        if self.sparkles is not None:
            self.sparkles.update(dt)
        if self.trail is not None:
            self.trail.options.update(stage=self.appearance, grounded=self.grounded)
            self.trail.update(dt)
            if not self.trail.done():
                if not self.samples or (self.x, self.y) != (self.samples[-1]['x'], self.samples[-1]['y']):
                    self.samples.append({
                        'x': self.x, 'y': self.y, 'time': self.elapsed,
                        'rect': tuple(self.animation.frame['rect_top_left']),
                        'size': self.data['cell_size'][0] * self.zoom,
                        'anchor': tuple(value * 128 / self.data['cell_size'][0]
                                        for value in self.data['anchor_px']),
                        'facing': -1 if self.flip else 1,
                    })
        self.samples[:] = [sample for sample in self.samples if self.elapsed - sample['time'] < .2]

    def draw(self):
        if self.image is None:
            self.image = p.load_image(str(self.assets / self.data['atlas']))
        if self.appearance not in self.glow_images:
            preset = self.glow['presets'][self.appearance - 1]
            self.glow_images[self.appearance] = p.load_image(str(self.assets / preset['file']))
        if self.sparkles is None:
            self.sparkles = Sparkles()
            self.sparkles.time_ms = self.elapsed * 1000
        if self.trail is not None and self.appearance > 1:
            if self.echoes is None:
                self.echoes = MotionEchoes(load_rgba(self.assets / self.data['atlas']))
            self.echoes.draw(self.samples, self.elapsed, stage=self.appearance)
            self.trail.draw(self.x, self.y, scale=self.zoom * 2, flip=self.flip,
                            angle=self.effect_angle, layer='back')

        frame = self.animation.frame
        width, height = self.data['cell_size']
        anchor_x, anchor_y = self.data['anchor_px']
        offset_x = (width / 2 - anchor_x) * self.zoom
        cx = self.x - offset_x if self.flip else self.x + offset_x
        cy = self.y + (anchor_y - height / 2) * self.zoom
        flip = 'h' if self.flip else ''
        cell = self.glow['cell_size']
        left, top, _, _ = frame['rect_top_left']
        glow_left = left // width * cell
        glow_bottom = (self.data['atlas_size'][1] // height - 1 - top // height) * cell
        self.glow_images[self.appearance].clip_composite_draw(
            glow_left, glow_bottom, cell, cell, 0, flip,
            cx, cy, cell * self.zoom, cell * self.zoom,
        )
        self.image.clip_composite_draw(
            *frame['pico2d_clip_rect'], 0, flip,
            cx, cy, width * self.zoom, height * self.zoom,
        )
        self.sparkles.draw(self.appearance - 1, self.x, self.y, self.zoom, self.flip)

    def close(self):
        # SDL 창을 닫기 전에 텍스처 참조를 해제한다.
        if self.trail is not None:
            self.trail.close()
            self.trail = None
        if self.echoes is not None:
            self.echoes.close()
            self.echoes = None
        self.samples.clear()
        self.image = None
        self.glow_images.clear()
        self.sparkles = None
