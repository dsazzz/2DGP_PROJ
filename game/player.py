"""플레이어의 게임 상태·이동·충돌·자원. 렌더링 모듈에 의존하지 않는다."""
import json
import math

from transitions import Machine

from game.paths import ART_ROOT
from game.collision import AABB, MoveResult, first_contact_time, move_and_collide, sweep_and_collide


SETTINGS = json.loads((ART_ROOT / 'player' / 'player-settings.json').read_text(encoding='utf-8'))
MOVEMENT = SETTINGS['movement']
MOVE_SPEEDS = tuple(MOVEMENT['move_speeds'])
JUMP_SPEED, GRAVITY, DASH_SPEED = (
    MOVEMENT[key] for key in ('jump_speed', 'gravity', 'dash_speed')
)
DASH_DURATION = MOVEMENT['dash_duration']
DEATH_DURATION = SETTINGS['death']['duration']


class Player:
    """입력 의도로 상태와 월드 좌표를 갱신한다. 표현은 PlayerView가 읽는다."""

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

    def __init__(self, x=320, y=128, body_size=None):
        self.x, self.y = x, y
        self.body_width, self.body_height = SETTINGS['body_size'] if body_size is None else body_size
        self.start_x, self.start_y = x, y
        # 같은 상태로 재진입하거나 초기화되는 경우도 구분한다.
        self.state_revision = self.reset_revision = 0
        self.machine = Machine(
            model=self, states=self.STATES, transitions=self.TRANSITIONS,
            initial='IDLE', auto_transitions=False, after_state_change='_state_changed',
        )
        self.reset()

    def _state_changed(self, *args, **kwargs):
        self.state_revision += 1

    def reset(self):
        """시작 위치·행동·자원을 복구한다. 표현·입력·카메라는 호출 쪽에서 관리한다."""
        self.reset_state()

    def _reset_values(self):
        self.reset_revision += 1
        self.x, self.y = self.start_x, self.start_y
        self.speed_level = 1
        self.move_speed = MOVE_SPEEDS[0]
        self.move_direction = self.vy = 0
        self.facing = 1
        self.grounded = self.can_jump = True
        self.dashes = MOVEMENT['dash_charges']
        self.dash_left = self.dash_vx = self.dash_vy = 0.0
        self.jump_age, self.land_left = 10.0, 0.0
        self.death_elapsed = 0.0
        self.death_direction = -1
        self.contact = MoveResult(self.body)
        # 이번 갱신의 (시작 상자, dx, dy, 시작 초, 이동 초). 흡수 등 외부 트리거가 읽는다.
        self.movement_paths = []

    def die(self, direction=None):
        """현재 위치에서 사망한다. 중복 판정은 기존 연출을 다시 시작하지 않는다."""
        if self.state != 'DEAD':
            self.start_death(direction)

    def on_enter_DEAD(self, direction=None):
        direction = -self.facing if direction is None else direction
        self.death_direction = 1 if direction >= 0 else -1
        self.death_elapsed = 0.0
        self.move_direction = self.vy = 0
        self.dash_left = self.dash_vx = self.dash_vy = self.land_left = 0.0
        self.can_jump = self.grounded = False
        self.contact = MoveResult(self.body)

    @property
    def death_complete(self):
        return self.state == 'DEAD' and self.death_elapsed >= DEATH_DURATION

    def on_enter_JUMP(self):
        self.vy = self.jump_speed
        self.grounded = self.can_jump = False
        self.dash_left = self.land_left = 0.0
        self.jump_age = 0.0

    def on_enter_DASH(self, dx, dy):
        if dx == dy == 0:
            dx = self.facing
        if dx:
            self.facing = 1 if dx > 0 else -1
        self.dash_left = DASH_DURATION
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

    def recover_dash(self):
        """대시를 1회 회복한다. 행동과 이동은 유지하고 최대 횟수를 넘지 않는다."""
        if self.state != 'DEAD':
            self.dashes = min(self.dashes + 1, MOVEMENT['dash_charges'])

    @property
    def speed_multiplier(self):
        return MOVE_SPEEDS[self.speed_level - 1] / MOVE_SPEEDS[0]

    @property
    def jump_speed(self):
        return JUMP_SPEED * self.speed_multiplier

    @property
    def gravity(self):
        # 상승·낙하 시간은 줄이되 점프 높이 v²/(2g)는 유지한다.
        return GRAVITY * self.speed_multiplier ** 2

    def set_speed_level(self, level):
        """이동과 공중 동작의 단계를 바꾼다. 위치·행동·대시는 유지한다."""
        if self.state != 'DEAD':
            before = self.speed_multiplier
            self.speed_level = max(1, min(level, len(MOVE_SPEEDS)))
            self.move_speed = MOVE_SPEEDS[self.speed_level - 1]
            if not self.grounded:
                self.vy *= self.speed_multiplier / before

    def increase_speed_level(self):
        """한 단계 올린다. 단계 수와 속도는 설정표를 따른다."""
        self.set_speed_level(self.speed_level + 1)

    def land(self, height):
        """실제 아래쪽 접촉에서 착지와 자원 회복을 반영한다."""
        if self.state == 'DEAD':
            return
        if not self.grounded:
            self.dashes = MOVEMENT['dash_charges']
            self.can_jump = True
            self.land_left = MOVEMENT['land_time']
        self.y, self.vy, self.grounded = height, 0.0, True

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
        self.movement_paths.clear()
        if self.state == 'DEAD':
            self.death_elapsed += dt
            return
        solids, one_way, hazards = tuple(solids), tuple(one_way), tuple(hazards)
        if self._check_danger(self.body, 0, 0, hazards, death_y):
            return
        self.contact = MoveResult(self.body)
        self._update_motion(dt, solids, one_way, hazards, death_y)
        if self.state != 'DEAD':
            self._update_state()

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

    def _move(self, dx, dy, solids, one_way, hazards, death_y, *, straight=False,
              offset=0.0, duration=0.0):
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
            # 지형에 막히기 전의 실제 경로와 이동 시간을 트리거 판정에 제공한다.
            if path_dx and dx:
                ratio = abs(path_dx / dx)
            else:
                ratio = abs(path_dy / dy) if path_dy and dy else 0.0
            self.movement_paths.append((box, path_dx, path_dy, offset, duration * ratio))
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
                                solids, one_way, hazards, death_y, straight=True, duration=dash_dt)
            if self.state == 'DEAD':
                return
            self.dash_left = max(0.0, self.dash_left - dash_dt)
            if (result.hit_left or result.hit_right or result.hit_top
                    or result.hit_bottom and self.dash_vy < 0):
                self.dash_left = self.dash_vx = self.dash_vy = 0.0
        normal_dt = dt - dash_dt
        if normal_dt:
            gravity = self.gravity
            dy = self.vy * normal_dt - gravity * normal_dt ** 2 / 2
            self.vy -= gravity * normal_dt
            self._move(self.move_direction * self.move_speed * normal_dt, dy,
                       solids, one_way, hazards, death_y, offset=dash_dt, duration=normal_dt)
            if self.state == 'DEAD':
                return
            if self.move_direction:
                self.facing = self.move_direction
        elif not dash_dt:
            self._move(0, 0, solids, one_way, hazards, death_y)

    def _update_state(self):
        if self.state == 'DASH' and self.dash_left > 0:
            return
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
