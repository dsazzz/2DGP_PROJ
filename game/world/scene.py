"""Playable scene: input, world state and gameplay coordination."""

import sdl2 as s

from game.core.camera import Camera
from game.core.display import LOGICAL_SIZE
from game.core.collision import AABB, first_contact_time
from game.objects.models import AbsorbSource, DisappearingPlatform, Electric, JumpPlatform, MovingPlatform
from game.objects.player import ACTION_BUFFER, MOVEMENT, Player


HORIZONTAL_KEYS = {s.SDLK_LEFT: -1, s.SDLK_a: -1, s.SDLK_RIGHT: 1, s.SDLK_d: 1}
VERTICAL_KEYS = {s.SDLK_DOWN: -1, s.SDLK_s: -1, s.SDLK_UP: 1, s.SDLK_w: 1}
DASH_KEYS = (s.SDLK_x, s.SDLK_LSHIFT, s.SDLK_RSHIFT)
JUMP_KEYS = (s.SDLK_SPACE, s.SDLK_z)


class PlayScene:
    def __init__(self, level_data):
        self.data = level_data
        self.bounds = AABB(0, 0, *self.data['size'])
        self.floors = tuple(AABB(*area) for area in self.data['floor'])
        self.platforms = tuple(AABB(*area) for area in self.data['platforms'])
        self.solids = self.floors + self.platforms + (
            AABB(-32, 0, 32, self.bounds.height),
            AABB(self.bounds.width, 0, 32, self.bounds.height),
        )
        self.one_way = tuple(AABB(*area) for area in self.data['one_way'])
        self.electric = Electric(self.data['electric'])
        self.hazards = self.electric.hazards
        self.sources = tuple(AbsorbSource(AABB(*area)) for area in self.data['sources'])
        self.moving = tuple(MovingPlatform(AABB(*obj['area']), obj['end_x'], obj['speed'])
                            for obj in self.data['moving'])
        self.disappearing = tuple(DisappearingPlatform(AABB(*obj['area']),
                                  obj.get('warning_time', .5), obj.get('hidden_time', 2))
                                  for obj in self.data['disappearing'])
        self.jump_platforms = tuple(JumpPlatform(AABB(*obj['area']), obj['launch_height'])
                                   for obj in self.data['jump_platforms'])
        self.exit = AABB(*self.data['exit']) if self.data['exit'] is not None else None
        self.player = Player(*self.data['checkpoints'][0]['spawn'])
        self.camera = Camera(self.bounds, size=LOGICAL_SIZE)
        self.held_keys = {}
        self.view = None
        self.restart(full=True)

    def open(self):
        # 데이터·물리 검증에는 SDL 리소스를 만들지 않아도 된다.
        from game.world.view import WorldView
        self.view = WorldView(self)

    @property
    def active_one_way(self):
        return (self.one_way + tuple(obj.area for obj in self.disappearing if obj.collidable)
                + tuple(obj.area for obj in self.jump_platforms))

    @property
    def section(self):
        return next((section for section in reversed(self.data['sections'])
                     if self.player.x >= section['x']), {'hint': ''})

    @property
    def absorbed(self):
        return sum(source.consumed for source in self.sources)

    def restart(self, *, full=False):
        if full:
            self.checkpoint = 0
            self.saved_level = 1
            self.saved_sources = (False,) * len(self.sources)
            self.deaths = 0
            self.elapsed = 0.0
        self.player.start_x, self.player.start_y = self.data['checkpoints'][self.checkpoint]['spawn']
        self.player.reset()
        self.player.set_speed_level(self.saved_level)
        for source, consumed in zip(self.sources, self.saved_sources):
            source.reset()
            source.consumed = consumed
        for obj in self.moving + self.disappearing + self.jump_platforms:
            obj.reset()
        self._clear_input()
        self.paused = self.complete = self._was_dead = False
        self.checkpoint_flash = 0.0
        self.camera.snap(self.player.x, self.player.y + self.player.body_height / 2)
        if self.view is not None:
            self.view.reset()

    def axes(self):
        return tuple(next((axis[key] for key in reversed(self.held_keys) if key in axis), 0)
                     for axis in (HORIZONTAL_KEYS, VERTICAL_KEYS))

    def _dash_axes(self, key, following):
        """같은 입력 묶음에서 행동 키와 방향 키를 함께 누른 경우를 읽는다."""
        dx, dy = self.axes()
        for event in following:
            if (event.type == s.SDL_WINDOWEVENT and event.window.event == s.SDL_WINDOWEVENT_FOCUS_LOST
                    or event.type == s.SDL_KEYUP and event.key.keysym.sym == key):
                break
            if event.type != s.SDL_KEYDOWN or event.key.repeat:
                continue
            direction = event.key.keysym.sym
            if direction in HORIZONTAL_KEYS:
                dx = HORIZONTAL_KEYS[direction]
            elif direction in VERTICAL_KEYS:
                dy = VERTICAL_KEYS[direction]
            else:
                break
        return dx, dy

    def _clear_input(self):
        self.held_keys.clear()
        self.player.set_vertical_input()
        self.player.jump_buffer_left = 0.0
        self._queued_actions = []
        self._pending_action = None
        self._clear_absorb_input()

    def _clear_absorb_input(self):
        self._absorb_input_left = 0.0
        self._absorb_direction = (0, 0)
        self._absorb_contacts = {}

    def handle_events(self, events):
        events = tuple(events)
        for index, event in enumerate(events):
            if event.type == s.SDL_KEYUP:
                key = event.key.keysym.sym
                self.held_keys.pop(key, None)
                if key in JUMP_KEYS and not any(button in self.held_keys for button in JUMP_KEYS):
                    self.player.set_vertical_input(down_held=self.player.down_held)
            elif (event.type == s.SDL_WINDOWEVENT
                  and event.window.event == s.SDL_WINDOWEVENT_FOCUS_LOST):
                self._clear_input()
                if not self.complete:
                    self.paused = True
            elif event.type == s.SDL_KEYDOWN:
                key = event.key.keysym.sym
                if event.key.repeat or key in self.held_keys:
                    continue
                self.held_keys[key] = None
                if key == s.SDLK_r:
                    full = s.SDLK_LSHIFT in self.held_keys or s.SDLK_RSHIFT in self.held_keys or self.complete
                    self.restart(full=full)
                    break
                if key == s.SDLK_RETURN:
                    if self.complete:
                        self.restart(full=True)
                        break
                    self.paused = False
                elif key == s.SDLK_p and not self.complete:
                    self.paused = not self.paused
                    self._clear_input()
                elif self.paused or self.complete or self.player.state == 'DEAD':
                    continue
                elif key in JUMP_KEYS + DASH_KEYS:
                    direction = self._dash_axes(key, events[index + 1:]) if key in DASH_KEYS else None
                    self._queued_actions.append(direction)

    def _consume_queued_actions(self):
        """한 물리 틱에서 입력을 누른 순서대로 한 번씩 꺼낸다."""
        actions, self._queued_actions = self._queued_actions, []
        for direction in actions:
            if direction is not None:
                self._request_dash(direction)
            else:
                self._pending_action = None
                self.player.queue_jump()
                if self.player.jump():
                    self._clear_absorb_input()

    def _buffer_action(self, direction):
        self._pending_action = self.elapsed + ACTION_BUFFER, direction

    def _start_buffered_action(self):
        if self.player.grounded and self.player.jump_buffer_left > 0 and self.player.jump():
            self._clear_absorb_input()
            return
        if self._pending_action is None:
            return
        deadline, direction = self._pending_action
        if self.elapsed > deadline:
            self._pending_action = None
        elif self.player.grounded and self.player.dash_left == 0:
            self._pending_action = None
            self._clear_absorb_input()
            self.player.dash(*direction)

    def _request_dash(self, direction):
        self.player.jump_buffer_left = 0.0
        if self.try_absorb(direction):
            return
        if self.player.dash_left > 0:
            self._absorb_input_left = MOVEMENT['absorb_input_buffer']
            self._absorb_direction = direction
            if self.player.grounded and self.player.dash_left <= ACTION_BUFFER:
                self._buffer_action(direction)
        elif self.player.dash(*direction):
            self._pending_action = None
            self._clear_absorb_input()
        else:
            self._buffer_action(direction)

    def try_absorb(self, direction):
        active = self.player.dash_left > 0
        if self.player.state == 'DEAD' or not (active or self._absorb_contacts):
            return False
        body = self.player.body
        if any(body.overlaps(area) for area in self.hazards):
            return False
        for source in self.sources:
            recent = self._absorb_contacts.get(source)
            contact = body if active and source.area.overlaps(body) else recent[1] if recent else None
            if contact is not None and source.try_absorb(contact):
                self._pending_action = None
                self._clear_absorb_input()
                self.player.redirect_dash(*direction, recent_contact=recent is not None)
                self.player.increase_speed_level()
                if self.view is not None:
                    self.view.player.play_absorb_effect()
                return True
        return False

    def _update_absorb_contacts(self, dt):
        """대시의 실제 이동 구간을 기억해 빠르게 지나친 직후의 재입력도 받는다."""
        self._absorb_contacts = {
            source: (left - dt, body) for source, (left, body) in self._absorb_contacts.items()
            if left > dt and not source.consumed
        }
        if not self.player.dash_paths:
            return
        grace = MOVEMENT['absorb_contact_grace']
        for source in self.sources:
            if source.consumed:
                continue
            for box, dx, dy, offset, duration in self.player.dash_paths:
                end = AABB(box.left + dx, box.bottom + dy, box.width, box.height)
                # 이동 끝에서 거꾸로 검사해 마지막으로 겹쳤던 시각을 얻는다.
                hit = first_contact_time(end, -dx, -dy, (source.area,))
                if hit is None or hit == 1:
                    continue
                left = grace - max(0.0, dt - offset - duration * (1 - hit))
                if left <= 0:
                    continue
                contact = end
                if not source.area.overlaps(end):
                    distance = min(1.0, hit + 1e-7)
                    contact = AABB(end.left - dx * distance, end.bottom - dy * distance, box.width, box.height)
                if source.area.overlaps(contact):
                    self._absorb_contacts[source] = left, contact

    def update(self, dt):
        if self.view is not None:
            self.view.remember_positions()
        if self.paused or self.complete:
            return
        left = s.SDLK_LEFT in self.held_keys or s.SDLK_a in self.held_keys
        right = s.SDLK_RIGHT in self.held_keys or s.SDLK_d in self.held_keys
        self.player.set_move_direction(right - left)
        self.player.set_vertical_input(
            jump_held=any(key in self.held_keys for key in JUMP_KEYS),
            down_held=s.SDLK_DOWN in self.held_keys or s.SDLK_s in self.held_keys,
        )
        if self._queued_actions and self.player.state != 'DEAD':
            self._consume_queued_actions()
        # 보류 중인 흡수는 같은 틱의 벽·위험 접촉보다 먼저 닿았는지까지 반영한다.
        horizon = min(dt, self.player.dash_left, self._absorb_input_left)
        if horizon > 0:
            hit = first_contact_time(
                self.player.body, self.player.dash_vx * horizon, self.player.dash_vy * horizon,
                (source.area for source in self.sources if not source.consumed),
            )
            if hit is not None and hit < 1:
                contact_dt = horizon * (hit + (1 - hit) * 1e-6)
                self._step(contact_dt)
                if not self.complete:
                    self._step(dt - contact_dt)
                return
        self._step(dt)

    def _step(self, dt):
        self.elapsed += dt
        self.checkpoint_flash = max(0.0, self.checkpoint_flash - dt)
        for platform in self.moving:
            platform.update(dt)
        for platform in self.disappearing:
            platform.update(dt, self.player.body)
        self._absorb_input_left = max(0.0, self._absorb_input_left - dt)
        self.player.update(dt, self.solids, one_way=self.active_one_way,
                           hazards=self.hazards, death_y=-32, moving_platforms=self.moving)
        self._update_absorb_contacts(dt)
        if self._absorb_input_left > 0:
            self.try_absorb(self._absorb_direction)
        if self.player.dash_left == 0:
            self._absorb_input_left = 0.0
        for platform in self.jump_platforms:
            platform.update(dt, self.player)
        for platform in self.disappearing:
            platform.trigger(self.player)
        if self.view is not None:
            self.view.update(dt)
        if self.player.state == 'DEAD':
            if not self._was_dead:
                self.deaths += 1
                self._was_dead = True
            self._clear_input()
            if self.player.death_complete:
                self.restart()
            return
        if self.player.grounded:
            for index, checkpoint in enumerate(self.data['checkpoints']):
                x, y = checkpoint['spawn']
                if index > self.checkpoint and self.player.body.overlaps(AABB(x - 24, y, 48, 64)):
                    self.checkpoint = index
                    self.saved_level = self.player.speed_level
                    self.saved_sources = tuple(source.consumed for source in self.sources)
                    self.checkpoint_flash = 1.5
            if self.exit is not None and self.player.body.overlaps(self.exit):
                self.complete = True
                self._clear_input()
                self.player.set_move_direction(0)
        if not self.complete:
            self._start_buffered_action()
        self.camera.follow(self.player.x, self.player.y + self.player.body_height / 2, dt)

    def draw(self, alpha=1.0):
        self.view.draw(1.0 if self.paused or self.complete else alpha)

    def close(self):
        if self.view is not None:
            self.view.close()
            self.view = None
