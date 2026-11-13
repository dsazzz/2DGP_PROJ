"""플레이어 상태를 읽어 애니메이션과 시각 효과의 수명을 관리한다."""
import json
import math

import pico2d as p

from game.paths import ART_ROOT
from game.collision import move_and_collide
from game.player import GRAVITY, MOVEMENT
from game.vfx.death import FREEZE_TIME, recoil_offset
from game.vfx.motion import MotionEchoes
from game.vfx.pico import PicoEffect, load_rgba
from game.vfx.sparkles import Sparkles


FALL_PREPARE_TIME = MOVEMENT['fall_prepare_time']


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


class PlayerView:
    """모델은 읽기만 한다. 이미지·애니메이션·효과·표현용 좌표는 여기서 소유한다."""
    def __init__(self, player, zoom=.5):
        self.player, self.zoom = player, zoom
        self.assets = ART_ROOT / 'player'
        self.data = json.loads((self.assets / 'player.json').read_text(encoding='utf-8-sig'))
        self.glow = json.loads((self.assets / 'player-glow.json').read_text(encoding='utf-8'))
        self.animation = Animation(self.data)
        self.appearance = self.glow['active_preset'] + 1
        self.image, self.glow_images = None, {}
        self.trail = self.echoes = self.sparkles = self.death_effect = None
        self.samples = []
        self.reset()

    @property
    def position(self):
        x, y = self.player.x, self.player.y
        if self.player.state == 'DEAD':
            dx, dy = recoil_offset(self.player.death_elapsed, self.player.death_direction)
            x, y = x + dx, y + dy
        return x, y

    def reset(self):
        self._close_effects()
        self.elapsed = self.clip_elapsed = self._death_age = 0.0
        self.flip = self.player.facing < 0
        self.landing_y = None
        self.death_origin = (self.player.x, self.player.y)
        self._reset_revision = self.player.reset_revision
        self._state_revision = self.player.state_revision
        self.play('idle')

    def set_appearance(self, stage):
        self.appearance = stage

    def play_absorb_effect(self):
        if self.player.state == 'DEAD':
            return
        if self.sparkles is None:
            self.sparkles = Sparkles()
        # 입력 직후에는 표현 갱신 전일 수 있으므로 최신 행동 방향을 읽는다.
        self.sparkles.trigger(self.appearance, self.player.facing < 0)

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
            self.trail = PicoEffect(effect, stage=self.appearance, grounded=self.player.grounded)

    def _air_clip(self):
        player = self.player
        if player.jump_age < MOVEMENT['jump_start_time']:
            return 'jump_start'
        if abs(player.vy) < MOVEMENT['apex_speed']:
            return 'jump_apex'
        if player.vy > 0:
            return 'jump_rise'
        t = FALL_PREPARE_TIME
        next_y = player.y + player.vy * t - GRAVITY * t * t / 2
        return 'fall' if self.landing_y is not None and next_y <= self.landing_y else 'fall_air'

    def _sync(self):
        player = self.player
        if self._reset_revision != player.reset_revision:
            self.reset()
        changed = self._state_revision != player.state_revision
        self.flip = player.facing < 0
        if player.state == 'DEAD':
            name = 'dead'
            if changed or self.death_effect is None:
                if self.sparkles is not None:
                    self.sparkles.close()
                self.death_origin = (player.x, player.y)
                self._death_age = 0.0
                self.death_effect = PicoEffect('death', stage=self.appearance)
        elif player.state == 'DASH':
            dx, dy = player.dash_vx, player.dash_vy
            if dy > 0:
                direction = 'up' if dx == 0 else 'up_right' if dx > 0 else 'up_left'
            elif dy < 0:
                direction = 'down' if dx == 0 else 'down_right' if dx > 0 else 'down_left'
            else:
                direction = 'right' if dx > 0 else 'left'
            mapping = self.data['dash_directions'][direction]
            self.flip = player.facing < 0 if mapping['flip_x'] == 'match_facing' else mapping['flip_x']
            name = mapping['clip']
        elif player.state in ('JUMP', 'FALL'):
            name = self._air_clip()
        else:
            name = {'IDLE': 'idle', 'RUN': 'run', 'LAND': 'land'}[player.state]
        if name != self.animation.name or changed and player.state != 'FALL':
            self.play(name)
        self._state_revision = player.state_revision

    def update(self, dt, solids=(), *, one_way=()):
        player = self.player
        self.landing_y = None
        if player.state != 'DEAD' and player.vy <= 0:
            t = FALL_PREPARE_TIME
            future = move_and_collide(player.body, player.move_direction * player.move_speed * t,
                                      player.vy * t - GRAVITY * t * t / 2,
                                      solids, one_way=one_way)
            if future.hit_bottom:
                self.landing_y = future.box.bottom
        self._sync()
        if player.state == 'DEAD':
            age = player.death_elapsed
            body_dt = max(0, age - FREEZE_TIME) - max(0, self._death_age - FREEZE_TIME)
            self.update_visuals(body_dt)
            self.death_effect.effect.time = age
            if self.death_effect.done():
                self.death_effect.close()
            self._death_age = age
        else:
            self.update_visuals(dt)

    def update_visuals(self, dt):
        self.elapsed += dt
        self.clip_elapsed += dt
        self.animation.update(dt)
        if self.sparkles is not None:
            self.sparkles.update(dt)
        x, y = self.position
        if self.trail is not None:
            self.trail.options.update(stage=self.appearance, grounded=self.player.grounded)
            self.trail.update(dt)
            if not self.trail.done():
                if not self.samples or (x, y) != (self.samples[-1]['x'], self.samples[-1]['y']):
                    self.samples.append({
                        'x': x, 'y': y, 'time': self.elapsed,
                        'rect': tuple(self.animation.frame['rect_top_left']),
                        'size': self.data['cell_size'][0] * self.zoom,
                        'anchor': tuple(value * 128 / self.data['cell_size'][0]
                                        for value in self.data['anchor_px']),
                        'facing': -1 if self.flip else 1,
                    })
        self.samples[:] = [sample for sample in self.samples if self.elapsed - sample['time'] < .2]

    def draw(self, offset=(0, 0)):
        if (self._state_revision != self.player.state_revision
                or self._reset_revision != self.player.reset_revision):
            self._sync()
        if self.player.death_complete:
            return
        px, py = self.position
        x, y = px - offset[0], py - offset[1]
        if self.image is None:
            self.image = p.load_image(str(self.assets / self.data['atlas']))
        if self.appearance not in self.glow_images:
            preset = self.glow['presets'][self.appearance - 1]
            self.glow_images[self.appearance] = p.load_image(str(self.assets / preset['file']))
        if self.trail is not None and self.appearance > 1:
            if self.echoes is None:
                self.echoes = MotionEchoes(load_rgba(self.assets / self.data['atlas']))
            self.echoes.draw(self.samples, self.elapsed, stage=self.appearance, offset=offset)
            self.trail.draw(x, y, scale=self.zoom * 2, flip=self.flip,
                            angle=-self.effect_angle if self.flip else self.effect_angle, layer='back')
        frame = self.animation.frame
        width, height = self.data['cell_size']
        anchor_x, anchor_y = self.data['anchor_px']
        offset_x = (width / 2 - anchor_x) * self.zoom
        cx = x - offset_x if self.flip else x + offset_x
        cy = y + (anchor_y - height / 2) * self.zoom
        flip = 'h' if self.flip else ''
        cell = self.glow['cell_size']
        left, top, _, _ = frame['rect_top_left']
        glow_left = left // width * cell
        glow_bottom = (self.data['atlas_size'][1] // height - 1 - top // height) * cell
        self.glow_images[self.appearance].clip_composite_draw(
            glow_left, glow_bottom, cell, cell, 0, flip, cx, cy, cell * self.zoom, cell * self.zoom,
        )
        self.image.clip_composite_draw(
            *frame['pico2d_clip_rect'], 0, flip, cx, cy, width * self.zoom, height * self.zoom,
        )
        if self.player.state == 'DEAD':
            self.death_effect.draw(self.death_origin[0] - offset[0], self.death_origin[1] - offset[1],
                                   scale=1, flip=self.player.death_direction < 0, layer='front')
        elif self.sparkles is not None:
            self.sparkles.draw(x, y, self.zoom)

    def _close_effects(self):
        for effect in (self.trail, self.echoes, self.sparkles, self.death_effect):
            if effect is not None:
                effect.close()
        self.trail = self.echoes = self.sparkles = self.death_effect = None
        self.samples.clear()

    def close(self):
        self._close_effects()
        self.image = None
        self.glow_images.clear()
