"""기존 플레이어의 이동·점프·8방향 대시와 애니메이션·시각 효과."""
import json
import math

import pico2d as p
from transitions import Machine

from game.paths import ART_ROOT
from game.vfx.sparkles import Sparkles
from game.vfx.motion import MotionEchoes
from game.vfx.pico import PicoEffect, load_rgba


MOVE_SPEED, JUMP_SPEED, GRAVITY, DASH_SPEED = 310, 690, 1800, 1450
FALL_PREPARE_TIME = .08


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
    """키 처리는 외부에서 하고, 전달받은 방향과 발 기준 월드 좌표로 이동한다."""

    STATES = ['IDLE', 'RUN', 'JUMP', 'FALL', 'DASH', 'LAND']
    TRANSITIONS = [
        {'trigger': 'start_run', 'source': ['IDLE', 'LAND', 'JUMP', 'FALL', 'DASH'], 'dest': 'RUN'},
        {'trigger': 'stop_run', 'source': ['RUN', 'LAND', 'JUMP', 'FALL', 'DASH'], 'dest': 'IDLE'},
        {'trigger': 'start_jump', 'source': '*', 'dest': 'JUMP'},
        {'trigger': 'start_fall', 'source': ['IDLE', 'RUN', 'JUMP', 'LAND', 'DASH'], 'dest': 'FALL'},
        {'trigger': 'start_dash', 'source': '*', 'dest': 'DASH'},
        {'trigger': 'touch_down', 'source': ['IDLE', 'RUN', 'JUMP', 'FALL', 'DASH'], 'dest': 'LAND'},
        {'trigger': 'reset_state', 'source': '*', 'dest': 'IDLE', 'before': '_reset_values'},
    ]

    def __init__(self, x=320, y=128, zoom=0.5):
        self.assets = ART_ROOT / 'player'
        self.data = json.loads((self.assets / 'player.json').read_text(encoding='utf-8-sig'))
        self.glow = json.loads((self.assets / 'player-glow.json').read_text(encoding='utf-8'))
        self.animation = Animation(self.data)
        self.x, self.y, self.zoom = x, y, zoom
        self.start_x, self.start_y = x, y
        self.move_speed = MOVE_SPEED
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
        # 예상 착지 높이는 외부에서 알려준다. 없으면 공중 낙하 자세를 쓴다.
        self.landing_y = None
        self.machine = Machine(
            model=self, states=self.STATES, transitions=self.TRANSITIONS,
            initial='IDLE', auto_transitions=False,
        )
        self.reset()

    def reset(self):
        self.reset_state()

    def _reset_values(self):
        self.x, self.y = self.start_x, self.start_y
        self.move_direction = 0
        self.vy = 0.0
        self.facing, self.flip = 1, False
        self.grounded = self.can_jump = True
        self.dashes = 2
        self.dash_left = self.dash_vx = self.dash_vy = 0.0
        self.jump_age, self.land_left = 10.0, 0.0
        self.elapsed = 0.0
        if self.sparkles is not None:
            self.sparkles.time_ms = 0.0

    def on_enter_IDLE(self):
        self.play('idle')

    def on_enter_RUN(self):
        self.play('run')

    def on_enter_LAND(self):
        self.play('land')

    def on_enter_FALL(self):
        self._update_air_animation()

    def on_enter_JUMP(self):
        self.vy = JUMP_SPEED
        self.grounded = self.can_jump = False
        self.dash_left = self.land_left = 0.0
        self.jump_age = 0.0
        self.play('jump_start')

    def on_enter_DASH(self, dx, dy):
        if dx == dy == 0:
            dx = self.facing
        if dx:
            self.facing = 1 if dx > 0 else -1
        if dy > 0:
            direction = 'up' if dx == 0 else 'up_right' if dx > 0 else 'up_left'
        elif dy < 0:
            direction = 'down' if dx == 0 else 'down_right' if dx > 0 else 'down_left'
        else:
            direction = 'right' if dx > 0 else 'left'
        mapping = self.data['dash_directions'][direction]
        self.flip = self.facing < 0 if mapping['flip_x'] == 'match_facing' else mapping['flip_x']
        self.play(mapping['clip'])
        self.dash_left = self.animation.clip['total_duration_ms'] / 1000
        length = math.hypot(dx, dy)
        self.dash_vx, self.dash_vy = dx / length * DASH_SPEED, dy / length * DASH_SPEED
        self.dashes -= 1
        self.can_jump = True
        self.vy = self.land_left = 0.0

    def jump(self):
        if self.can_jump:
            self.start_jump()

    def dash(self, dx=0, dy=0):
        if self.dashes > 0:
            self.start_dash(dx, dy)

    def land(self, height):
        """외부 접촉 판정에서 착지를 알린다. 지형 판정은 호출한 쪽에서 한다."""
        if not self.grounded:
            self.dashes = 2
            self.can_jump = True
            self.land_left = .1
        self.y, self.vy, self.grounded = height, 0.0, True

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

    def set_move_direction(self, direction):
        """좌(-1)·정지(0)·우(1) 의도를 저장한다. 행동 전환은 update에서 한다."""
        self.move_direction = (direction > 0) - (direction < 0)

    def update(self, dt, *, resolve_motion=None):
        self._update_motion(dt)
        if resolve_motion is not None:
            resolve_motion(self)
        else:
            self.grounded = False
        self._update_state()
        self.update_visuals(dt)

    def _update_motion(self, dt):
        self.jump_age += dt
        self.land_left = max(0.0, self.land_left - dt)
        # 대시 종료 시점을 나누어 프레임 주기에 따라 이동 거리가 달라지지 않게 한다.
        dash_dt = min(dt, self.dash_left)
        if dash_dt:
            self.x += self.dash_vx * dash_dt
            self.y += self.dash_vy * dash_dt
            self.dash_left = max(0.0, self.dash_left - dash_dt)
            if self.dash_vy > 0:
                self.grounded = False
        normal_dt = dt - dash_dt
        if normal_dt:
            self.x += self.move_direction * self.move_speed * normal_dt
            self.y += self.vy * normal_dt - GRAVITY * normal_dt ** 2 / 2
            self.vy -= GRAVITY * normal_dt
            if self.move_direction:
                self.facing = self.move_direction

    def _update_state(self):
        if self.state == 'DASH' and self.dash_left > 0:
            return
        self.flip = self.facing < 0
        if self.grounded:
            if self.move_direction:
                if self.state != 'RUN':
                    self.start_run()
            elif self.land_left > 0:
                if self.state != 'LAND':
                    self.touch_down()
            elif self.state != 'IDLE':
                self.stop_run()
        else:
            if (self.vy < 0 or self.state == 'DASH') and self.state != 'FALL':
                self.start_fall()
            self._update_air_animation()

    def _update_air_animation(self):
        if self.jump_age < .067:
            name = 'jump_start'
        elif abs(self.vy) < 110:
            name = 'jump_apex'
        elif self.vy > 0:
            name = 'jump_rise'
        else:
            t = FALL_PREPARE_TIME
            next_y = self.y + self.vy * t - GRAVITY * t * t / 2
            name = 'fall' if self.landing_y is not None and next_y <= self.landing_y else 'fall_air'
        if self.animation.name != name:
            self.play(name)

    def update_visuals(self, dt):
        """동작 미리보기에서도 물리 이동 없이 기존 표현만 재생할 수 있다."""
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
                            angle=-self.effect_angle if self.flip else self.effect_angle, layer='back')

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
