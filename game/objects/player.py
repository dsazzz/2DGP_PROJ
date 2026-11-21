"""플레이어의 게임 상태·이동·충돌·자원. 렌더링 모듈에 의존하지 않는다."""
import json
import math

from transitions import Machine

from game.core.paths import ART_ROOT
from game.core.collision import AABB, MoveResult, first_contact_time, move_and_collide, sweep_and_collide


SETTINGS = json.loads((ART_ROOT / 'player' / 'player-settings.json').read_text(encoding='utf-8'))
MOVEMENT = SETTINGS['movement']
MOVE_SPEEDS = tuple(MOVEMENT['move_speeds'])
RUN_ACCEL, RUN_REDUCE, AIR_MULT = (
    MOVEMENT[key] for key in ('run_accel', 'run_reduce', 'air_mult')
)
JUMP_SPEED, GRAVITY, DASH_SPEED = (
    MOVEMENT[key] for key in ('jump_speed', 'gravity', 'dash_speed')
)
JUMP_H_BOOST, VAR_JUMP_TIME, JUMP_GRACE_TIME, ACTION_BUFFER = (
    MOVEMENT[key] for key in ('jump_h_boost', 'var_jump_time', 'jump_grace_time', 'action_buffer')
)
APEX_SPEED, MAX_FALL, FAST_MAX_FALL = (
    MOVEMENT[key] for key in ('apex_speed', 'max_fall', 'fast_max_fall')
)
DASH_DURATION, END_DASH_SPEED = MOVEMENT['dash_duration'], MOVEMENT['end_dash_speed']
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
        self.move_direction = 0
        self.vx = self.vy = 0.0
        self.set_vertical_input()
        self.coyote_left = self.jump_buffer_left = 0.0
        self.facing = 1
        self.grounded = self.can_jump = True
        self.dashes = MOVEMENT['dash_charges']
        self.dash_left = self.dash_vx = self.dash_vy = 0.0
        self.jump_age, self.land_left = 10.0, 0.0
        self.death_elapsed = 0.0
        self.death_direction = -1
        self.contact = MoveResult(self.body)
        # 이번 갱신에 실제로 지나간 대시 구간과 소요 시간.
        self.dash_paths = []
        self._moving_platforms = ()
        self._motion_dt = 0.0

    def die(self, direction=None):
        """현재 위치에서 사망한다. 중복 판정은 기존 연출을 다시 시작하지 않는다."""
        if self.state != 'DEAD':
            self.start_death(direction)

    def on_enter_DEAD(self, direction=None):
        direction = -self.facing if direction is None else direction
        self.death_direction = 1 if direction >= 0 else -1
        self.death_elapsed = 0.0
        self.move_direction = 0
        self.vx = self.vy = 0.0
        self.set_vertical_input()
        self.coyote_left = self.jump_buffer_left = 0.0
        self.dash_left = self.dash_vx = self.dash_vy = self.land_left = 0.0
        self.can_jump = self.grounded = False
        self.contact = MoveResult(self.body)

    @property
    def death_complete(self):
        return self.state == 'DEAD' and self.death_elapsed >= DEATH_DURATION

    def on_enter_JUMP(self, speed=None):
        self.vy = self.jump_speed if speed is None else speed
        self.coyote_left = self.jump_buffer_left = self.var_jump_left = 0.0
        if speed is None:
            self.vx += JUMP_H_BOOST * self.speed_multiplier * self.move_direction
            if self.jump_held:
                self.var_jump_left = VAR_JUMP_TIME / self.speed_multiplier
        self.grounded = self.can_jump = False
        self.dash_left = self.land_left = 0.0
        self.jump_age = 0.0

    def on_enter_DASH(self, dx, dy, consume_charge=True):
        if dx == dy == 0:
            dx = self.facing
        if dx:
            self.facing = 1 if dx > 0 else -1
        self.dash_left = DASH_DURATION
        length = math.hypot(dx, dy)
        self.dash_vx, self.dash_vy = dx / length * DASH_SPEED, dy / length * DASH_SPEED
        if consume_charge:
            self.dashes = max(0, self.dashes - 1)
        self.coyote_left = self.jump_buffer_left = self.var_jump_left = 0.0
        self.can_jump = True
        self.vx = self.vy = self.land_left = 0.0

    def queue_jump(self):
        """점프 입력을 착지할 때까지 잠깐 보관한다."""
        self.jump_buffer_left = ACTION_BUFFER

    def jump(self):
        if self.state != 'DEAD' and self.can_jump:
            return self.start_jump()
        return False

    def bounce(self, height):
        """발판 등 외부 동작으로 위로 튕긴다. 현재 단계의 중력을 따른다."""
        if self.state != 'DEAD':
            self.start_jump(math.sqrt(2 * self.gravity * height))

    def dash(self, dx=0, dy=0):
        if self.state != 'DEAD' and self.dash_left == 0 and (self.grounded or self.dashes > 0):
            return self.start_dash(dx, dy)
        return False

    def redirect_dash(self, dx=0, dy=0, *, recent_contact=False):
        """대시 중이거나 장면이 방금 대시 접촉을 확인했을 때 방향을 바꾼다."""
        if self.state != 'DEAD' and (self.dash_left > 0 or recent_contact):
            self.start_dash(dx, dy, consume_charge=False)

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

    @property
    def near_apex(self):
        return abs(self.vy) < APEX_SPEED * self.speed_multiplier

    def vertical_motion(self, dt):
        """이번 구간의 세로 변위와 속도를 계산한다."""
        gravity = self.gravity
        if not self.grounded and self.jump_held and self.near_apex:
            gravity *= 0.5
        fall_limit = (FAST_MAX_FALL if self.down_held else MAX_FALL) * self.speed_multiplier
        vy = max(self.vy, -fall_limit)
        hold_time = min(dt, self.var_jump_left) if vy > 0 and self.jump_held else 0.0
        dt -= hold_time
        # 상한에 닿기 전은 가속하고, 남은 시간은 일정 속도로 떨어진다.
        gravity_time = min(dt, (vy + fall_limit) / gravity)
        dy = vy * (hold_time + gravity_time) - gravity * gravity_time ** 2 / 2
        dy -= fall_limit * (dt - gravity_time)
        return dy, max(-fall_limit, vy - gravity * dt)

    def set_speed_level(self, level):
        """이동과 공중 동작의 단계를 바꾼다. 위치·행동·대시는 유지한다."""
        if self.state != 'DEAD':
            before = self.speed_multiplier
            self.speed_level = max(1, min(level, len(MOVE_SPEEDS)))
            self.move_speed = MOVE_SPEEDS[self.speed_level - 1]
            ratio = self.speed_multiplier / before
            self.vx *= ratio
            if not self.grounded:
                self.vy *= ratio
                self.var_jump_left /= ratio

    def increase_speed_level(self):
        """한 단계 올린다. 단계 수와 속도는 설정표를 따른다."""
        self.set_speed_level(self.speed_level + 1)

    def land(self, height):
        """실제 아래쪽 접촉에서 착지와 자원 회복을 반영한다."""
        if self.state == 'DEAD':
            return
        if not self.grounded:
            self.can_jump = True
            self.land_left = MOVEMENT['land_time']
        self.dashes = MOVEMENT['dash_charges']
        self.coyote_left = self.var_jump_left = 0.0
        self.y, self.vy, self.grounded = height, 0.0, True

    def set_move_direction(self, direction):
        """좌(-1)·정지(0)·우(1) 의도를 저장한다. 행동 전환은 update에서 한다."""
        if self.state != 'DEAD':
            self.move_direction = (direction > 0) - (direction < 0)

    def set_vertical_input(self, *, jump_held=False, down_held=False):
        """점프 유지와 빠른 낙하에 쓰는 키 상태를 저장한다."""
        self.jump_held = jump_held
        self.down_held = down_held
        if not jump_held:
            self.var_jump_left = 0.0

    @property
    def body(self):
        return AABB(self.x - self.body_width / 2, self.y,
                    self.body_width, self.body_height)

    def update(self, dt, solids=(), *, one_way=(), hazards=(), death_y=None,
               moving_platforms=()):
        """위험 구역은 월드 AABB, death_y는 발이 내려가면 사망하는 높이다."""
        self.dash_paths.clear()
        if self.state == 'DEAD':
            self.death_elapsed += dt
            return
        solids, one_way, hazards = tuple(solids), tuple(one_way), tuple(hazards)
        if self._check_danger(self.body, 0, 0, hazards, death_y):
            return
        was_grounded = self.grounded
        self.jump_buffer_left = max(0.0, self.jump_buffer_left - dt)
        if self.coyote_left > 0:
            self.coyote_left = max(0.0, self.coyote_left - dt)
            if self.coyote_left <= 1e-9:
                self.coyote_left = 0.0
                self.can_jump = False
        self.contact = MoveResult(self.body)
        self._moving_platforms = tuple(moving_platforms)
        self._motion_dt = dt
        if self.grounded and not (self.dash_left and self.dash_vy > 0):
            rider = next((platform for platform in self._moving_platforms
                          if platform.supports(self.body, previous=True)), None)
            if rider is not None:
                self._moving_platforms = tuple(p for p in self._moving_platforms if p is not rider)
                self._move_static(rider.delta[0], 0, solids, one_way, hazards, death_y, duration=dt)
                if self.state == 'DEAD':
                    return
                if rider.supports(self.body):
                    # 접지를 유지하는 동안 대시는 쓸 수 있지만 착지 연출은 반복하지 않는다.
                    self.grounded = True
                    self.land(rider.area.top)
                one_way += (rider.area,)
        self._update_motion(dt, solids, one_way, hazards, death_y)
        if self.state != 'DEAD':
            if was_grounded and not self.grounded and not self.dash_left and self.can_jump:
                self.coyote_left = JUMP_GRACE_TIME
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
        if not self._moving_platforms or self._motion_dt == 0 or dy >= 0:
            return self._move_static(dx, dy, solids, one_way, hazards, death_y,
                                     straight=straight, offset=offset, duration=duration)
        solve = sweep_and_collide if straight else move_and_collide
        before = self.body
        static = solve(before, dx, dy, solids, one_way=one_way)
        start, end = offset / self._motion_dt, (offset + duration) / self._motion_dt
        # 일반 이동은 기존 X→Y 순서를 유지하고, 대시는 직선 접촉 시각을 사용한다.
        vertical_box = before if straight else AABB(
            static.box.left, before.bottom, before.width, before.height)
        limit = abs((static.box.bottom - before.bottom) / dy) if dy else 1.0
        if straight and dx:
            limit = min(limit, abs((static.box.left - before.left) / dx))
        contacts = []
        for platform in self._moving_platforms:
            time = platform.landing_time(vertical_box, dx if straight else 0, dy, start, end)
            if time is not None and time <= limit + 1e-9:
                contacts.append((time, platform))
        if not contacts:
            return self._move_static(dx, dy, solids, one_way, hazards, death_y,
                                     straight=straight, offset=offset, duration=duration)
        time, platform = min(contacts, key=lambda contact: contact[0])
        surface = platform.area_at(start + (end - start) * time)
        self._move_static(dx * time if straight else dx, surface.top - before.bottom,
                          solids, one_way, hazards, death_y, straight=straight,
                          offset=offset, duration=duration * time)
        if self.state == 'DEAD':
            return MoveResult(self.body)
        if not math.isclose(self.y, surface.top, rel_tol=0, abs_tol=1e-7):
            return self.contact
        self.land(surface.top)
        destination = platform.area_at(end)
        self._move_static(destination.left - surface.left, 0,
                          solids, one_way, hazards, death_y,
                          offset=offset + duration * time, duration=duration * (1 - time))
        if self.state == 'DEAD':
            return MoveResult(self.body)
        if (self.body.left < destination.right and self.body.right > destination.left
                and math.isclose(self.y, destination.top, rel_tol=0, abs_tol=1e-7)):
            self.grounded = True
            self.land(destination.top)
        contact = self.contact
        self.contact = MoveResult(self.body, contact.hit_left, contact.hit_right,
                                  self.grounded, contact.hit_top)
        return MoveResult(self.body, contact.hit_left, contact.hit_right, True, contact.hit_top)

    def _move_static(self, dx, dy, solids, one_way, hazards, death_y, *, straight=False,
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
            if straight:
                # 지형에 막히기 전까지 실제로 이동한 시간과 경로다.
                ratio = abs(path_dx / dx) if dx else abs(path_dy / dy) if dy else 0.0
                self.dash_paths.append((box, path_dx, path_dy, offset, duration * ratio))
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
            self.vy = self.var_jump_left = 0.0
        if result.hit_left or result.hit_right:
            self.vx = 0.0
        previous = self.contact
        self.contact = MoveResult(
            self.body, previous.hit_left or result.hit_left,
            previous.hit_right or result.hit_right,
            previous.hit_bottom or bottom, previous.hit_top or result.hit_top,
        )
        return result

    def _update_run_velocity(self, dt):
        """수평 속도를 입력에 맞추고 최고속도를 넘으면 천천히 낮춘다."""
        multiplier = self.speed_multiplier
        if abs(self.vx) > self.move_speed and self.vx * self.move_direction >= 0:
            speed = max(self.move_speed, abs(self.vx) - RUN_REDUCE * multiplier ** 2 * dt)
            self.vx = math.copysign(speed, self.vx)
            return
        target = self.move_direction * self.move_speed
        change = RUN_ACCEL * multiplier * dt
        if not self.grounded:
            change *= AIR_MULT
        self.vx += max(-change, min(change, target - self.vx))

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
            self.dash_left -= dash_dt
            hit_wall = result.hit_left or result.hit_right
            if (self.dash_left <= 1e-9 or hit_wall or result.hit_top
                    or result.hit_bottom and self.dash_vy < 0):
                self.vx = 0.0 if hit_wall else self.dash_vx * END_DASH_SPEED / DASH_SPEED
                self.dash_left = self.dash_vx = self.dash_vy = 0.0
        normal_dt = dt - dash_dt
        if normal_dt:
            self._update_run_velocity(normal_dt)
            dy, self.vy = self.vertical_motion(normal_dt)
            self.var_jump_left = max(0.0, self.var_jump_left - normal_dt)
            self._move(self.vx * normal_dt, dy,
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
            if self.move_direction or self.vx:
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
