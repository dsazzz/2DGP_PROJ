"""플레이어의 이동·점프·대시·사망 상태와 애니메이션·시각 효과."""
import json
import math

import pico2d as p
from transitions import Machine

from game.paths import ART_ROOT
from game.collision import AABB, MoveResult, first_contact_time, move_and_collide, sweep_and_collide
from game.vfx.sparkles import Sparkles
from game.vfx.motion import MotionEchoes
from game.vfx.pico import PicoEffect, load_rgba
from game.vfx.death import FREEZE_TIME, DURATION as DEATH_DURATION, recoil_offset


SETTINGS = json.loads((ART_ROOT / 'player' / 'player-settings.json').read_text(encoding='utf-8'))
MOVEMENT = SETTINGS['movement']
MOVE_SPEED, JUMP_SPEED, GRAVITY, DASH_SPEED = (
    MOVEMENT[key] for key in ('move_speed', 'jump_speed', 'gravity', 'dash_speed')
)
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


class Player:
    """키 처리는 외부에서 하고, 전달받은 방향과 발 기준 월드 좌표로 이동한다."""

    ACTIVE_STATES = ['IDLE', 'RUN', 'JUMP', 'FALL', 'DASH', 'LAND']
    STATES = ACTIVE_STATES + ['DEAD']
    TRANSITIONS = [
        {'trigger': 'start_run', 'source': ['IDLE', 'LAND', 'JUMP', 'FALL', 'DASH'], 'dest': 'RUN'},
        {'trigger': 'stop_run', 'source': ['RUN', 'LAND', 'JUMP', 'FALL', 'DASH'], 'dest': 'IDLE'},
        {'trigger': 'start_jump', 'source': ACTIVE_STATES, 'dest': 'JUMP'},
        {'trigger': 'start_fall', 'source': ['IDLE', 'RUN', 'JUMP', 'LAND', 'DASH'], 'dest': 'FALL'},
        {'trigger': 'start_dash', 'source': ACTIVE_STATES, 'dest': 'DASH'},
        {'trigger': 'touch_down', 'source': ['IDLE', 'RUN', 'JUMP', 'FALL', 'DASH'], 'dest': 'LAND'},
        {'trigger': 'start_death', 'source': ACTIVE_STATES, 'dest': 'DEAD'},
        {'trigger': 'reset_state', 'source': '*', 'dest': 'IDLE', 'before': '_reset_values'},
    ]

    def __init__(self, x=320, y=128, zoom=0.5, body_size=None):
        self.assets = ART_ROOT / 'player'
        self.data = json.loads((self.assets / 'player.json').read_text(encoding='utf-8-sig'))
        self.glow = json.loads((self.assets / 'player-glow.json').read_text(encoding='utf-8'))
        self.animation = Animation(self.data)
        self.x, self.y, self.zoom = x, y, zoom
        # 월드 단위의 임시 몸체 크기. 그림 배율·프레임·꼬리와 독립적이다.
        self.body_width, self.body_height = SETTINGS['body_size'] if body_size is None else body_size
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
        # 가까운 미래의 지형 접촉으로 착지 준비 자세를 선택한다.
        self.landing_y = None
        self.death_effect = None
        self.death_elapsed = 0.0
        self.death_origin = (x, y)
        self.death_direction = -1
        self.machine = Machine(
            model=self, states=self.STATES, transitions=self.TRANSITIONS,
            initial='IDLE', auto_transitions=False,
        )
        self.reset()

    def reset(self):
        self.reset_state()

    def _reset_values(self):
        if self.death_effect is not None:
            self.death_effect.close()
            self.death_effect = None
        self.death_elapsed = 0.0
        self.x, self.y = self.start_x, self.start_y
        self.move_direction = 0
        self.vy = 0.0
        self.facing, self.flip = 1, False
        self.grounded = self.can_jump = True
        self.dashes = MOVEMENT['dash_charges']
        self.dash_left = self.dash_vx = self.dash_vy = 0.0
        self.jump_age, self.land_left = 10.0, 0.0
        self.elapsed = 0.0
        self.contact = MoveResult(self.body)
        self.landing_y = None
        if self.sparkles is not None:
            self.sparkles.time_ms = 0.0

    def on_enter_IDLE(self):
        self.play('idle')

    def on_enter_RUN(self):
        self.play('run')

    def on_enter_LAND(self):
        self.play('land')

    def die(self, direction=None):
        """현재 위치에서 사망한다. 중복 판정은 기존 연출을 다시 시작하지 않는다."""
        if self.state != 'DEAD':
            self.start_death(direction)

    def on_enter_DEAD(self, direction=None):
        self.death_origin = (self.x, self.y)
        if direction is None:
            direction = 1 if self.flip else -1
        self.death_direction = 1 if direction >= 0 else -1
        self.death_elapsed = 0.0
        self.move_direction = self.vy = 0
        self.dash_left = self.dash_vx = self.dash_vy = self.land_left = 0.0
        self.can_jump = self.grounded = False
        self.landing_y = None
        self.contact = MoveResult(self.body)
        self.play('dead')
        self.death_effect = PicoEffect('death', stage=self.appearance)

    @property
    def death_complete(self):
        return self.state == 'DEAD' and self.death_elapsed >= DEATH_DURATION

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
        if self.state != 'DEAD' and self.can_jump:
            self.start_jump()

    def dash(self, dx=0, dy=0):
        if self.state != 'DEAD' and self.dashes > 0:
            self.start_dash(dx, dy)

    def land(self, height):
        """실제 아래쪽 접촉에서 착지와 자원 회복을 반영한다."""
        if self.state == 'DEAD':
            return
        if not self.grounded:
            self.dashes = MOVEMENT['dash_charges']
            self.can_jump = True
            self.land_left = MOVEMENT['land_time']
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
        if self.state != 'DEAD':
            self.move_direction = (direction > 0) - (direction < 0)

    @property
    def body(self):
        return AABB(self.x - self.body_width / 2, self.y,
                    self.body_width, self.body_height)

    def update(self, dt, solids=(), *, one_way=(), hazards=(), death_y=None):
        """위험 구역은 월드 AABB, death_y는 발이 내려가면 사망하는 높이다."""
        if self.state == 'DEAD':
            self._update_death(dt)
            return
        solids, one_way, hazards = tuple(solids), tuple(one_way), tuple(hazards)
        if self._check_danger(self.body, 0, 0, hazards, death_y):
            return
        self.contact = MoveResult(self.body)
        self._update_motion(dt, solids, one_way, hazards, death_y)
        if self.state == 'DEAD':
            return
        self.landing_y = None
        if self.vy <= 0:
            t = FALL_PREPARE_TIME
            future = move_and_collide(
                self.body, self.move_direction * self.move_speed * t,
                self.vy * t - GRAVITY * t * t / 2, solids, one_way=one_way,
            )
            if future.hit_bottom:
                self.landing_y = future.box.bottom
        self._update_state()
        self.update_visuals(dt)

    def _update_death(self, dt):
        previous = self.death_elapsed
        self.death_elapsed += dt
        body_dt = max(0, self.death_elapsed - FREEZE_TIME) - max(0, previous - FREEZE_TIME)
        self.update_visuals(body_dt)
        dx, dy = recoil_offset(self.death_elapsed, self.death_direction)
        self.x, self.y = self.death_origin[0] + dx, self.death_origin[1] + dy
        self.death_effect.update(dt)
        if self.death_effect.done():
            self.death_effect.close()

    def _check_danger(self, box, dx, dy, hazards, death_y):
        time = first_contact_time(box, dx, dy, hazards)
        if death_y is not None and box.bottom + dy < death_y:
            fall_time = 0.0 if box.bottom < death_y else (death_y - box.bottom) / dy
            time = fall_time if time is None else min(time, fall_time)
        if time is None:
            return False
        self.x = box.left + box.width / 2 + dx * time
        self.y = box.bottom + dy * time
        # 가로 진입 방향과 반대로 튕긴다. 세로 진입이면 현재 바라보는 방향을 쓴다.
        self.die(-1 if dx > 0 else 1 if dx < 0 else None)
        return True

    def _move(self, dx, dy, solids, one_way, hazards, death_y, *, straight=False):
        solve = sweep_and_collide if straight else move_and_collide
        before = self.body
        result = solve(before, dx, dy, solids, one_way=one_way)
        actual_dx, actual_dy = result.box.left - before.left, result.box.bottom - before.bottom
        if straight:
            paths = ((before, actual_dx, actual_dy),)
        else:
            after_x = AABB(result.box.left, before.bottom, before.width, before.height)
            paths = ((before, actual_dx, 0), (after_x, 0, actual_dy))
        for box, path_dx, path_dy in paths:
            if self._check_danger(box, path_dx, path_dy, hazards, death_y):
                return MoveResult(self.body)
        self.x = result.box.left + self.body_width / 2
        self.y = result.box.bottom
        bottom = result.hit_bottom
        if not bottom and dy <= 0:
            # 수평 대시도 바닥 지지를 검사한다. 옆면 접촉은 접지로 보지 않는다.
            support = move_and_collide(self.body, 0, -1e-6, solids, one_way=one_way)
            if support.hit_bottom:
                bottom = True
                self.y = support.box.bottom
        if bottom:
            self.land(self.y)
        else:
            self.grounded = False
        if result.hit_top:
            self.vy = 0.0
        previous = self.contact
        self.contact = MoveResult(
            self.body, previous.hit_left or result.hit_left,
            previous.hit_right or result.hit_right,
            previous.hit_bottom or bottom, previous.hit_top or result.hit_top,
        )
        return result

    def _update_motion(self, dt, solids, one_way, hazards, death_y):
        self.jump_age += dt
        self.land_left = max(0.0, self.land_left - dt)
        # 대시 종료 시점을 나누어 프레임 주기에 따라 이동 거리가 달라지지 않게 한다.
        dash_dt = min(dt, self.dash_left)
        if dash_dt:
            result = self._move(self.dash_vx * dash_dt, self.dash_vy * dash_dt,
                                solids, one_way, hazards, death_y, straight=True)
            if self.state == 'DEAD':
                return
            self.dash_left = max(0.0, self.dash_left - dash_dt)
            if (result.hit_left or result.hit_right or result.hit_top
                    or result.hit_bottom and self.dash_vy < 0):
                self.dash_left = self.dash_vx = self.dash_vy = 0.0
        normal_dt = dt - dash_dt
        if normal_dt:
            dy = self.vy * normal_dt - GRAVITY * normal_dt ** 2 / 2
            self.vy -= GRAVITY * normal_dt
            self._move(self.move_direction * self.move_speed * normal_dt, dy,
                       solids, one_way, hazards, death_y)
            if self.state == 'DEAD':
                return
            if self.move_direction:
                self.facing = self.move_direction
        elif not dash_dt:
            self._move(0, 0, solids, one_way, hazards, death_y)

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
            if (self.vy <= 0 or self.state == 'DASH') and self.state != 'FALL':
                self.start_fall()
            self._update_air_animation()

    def _update_air_animation(self):
        if self.jump_age < MOVEMENT['jump_start_time']:
            name = 'jump_start'
        elif abs(self.vy) < MOVEMENT['apex_speed']:
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

    def draw(self, offset=(0, 0)):
        """카메라 원점만 빼서 그린다. 월드 위치와 잔상 기록은 유지한다."""
        if self.death_complete:
            return
        x, y = self.x - offset[0], self.y - offset[1]
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
            glow_left, glow_bottom, cell, cell, 0, flip,
            cx, cy, cell * self.zoom, cell * self.zoom,
        )
        self.image.clip_composite_draw(
            *frame['pico2d_clip_rect'], 0, flip,
            cx, cy, width * self.zoom, height * self.zoom,
        )
        if self.state == 'DEAD':
            self.death_effect.draw(self.death_origin[0] - offset[0],
                                   self.death_origin[1] - offset[1], scale=1,
                                   flip=self.death_direction < 0, layer='front')
        else:
            self.sparkles.draw(self.appearance - 1, x, y, self.zoom, self.flip)

    def close(self):
        # SDL 창을 닫기 전에 텍스처 참조를 해제한다.
        if self.death_effect is not None:
            self.death_effect.close()
            self.death_effect = None
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
