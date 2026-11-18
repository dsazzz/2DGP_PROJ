"""Playable scene: input, world state and gameplay coordination."""

import sdl2 as s

from game.core.camera import Camera
from game.core.display import LOGICAL_SIZE
from game.core.collision import AABB, first_contact_time
from game.objects.models import AbsorbSource, DisappearingPlatform, Electric, JumpPlatform, MovingPlatform
from game.objects.player import MOVEMENT, Player


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
        self.held_keys = set()
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
        self.held_keys.clear()
        self._clear_absorb_input()
        self.paused = self.complete = self._was_dead = False
        self.checkpoint_flash = 0.0
        self.camera.snap(self.player.x, self.player.y + self.player.body_height / 2)
        if self.view is not None:
            self.view.reset()

    def axes(self):
        keys = self.held_keys
        right = bool(keys & {s.SDLK_RIGHT, s.SDLK_d})
        left = bool(keys & {s.SDLK_LEFT, s.SDLK_a})
        up = bool(keys & {s.SDLK_UP, s.SDLK_w})
        down = bool(keys & {s.SDLK_DOWN, s.SDLK_s})
        return int(right) - int(left), int(up) - int(down)

    def _clear_absorb_input(self):
        self._absorb_input_left = 0.0
        self._absorb_direction = (0, 0)
        self._absorb_contacts = {}

    def handle_events(self, events):
        for event in events:
            if event.type == s.SDL_KEYUP:
                self.held_keys.discard(event.key.keysym.sym)
            elif (event.type == s.SDL_WINDOWEVENT
                  and event.window.event == s.SDL_WINDOWEVENT_FOCUS_LOST):
                self.held_keys.clear()
                self._clear_absorb_input()
                if not self.complete:
                    self.paused = True
            elif event.type == s.SDL_KEYDOWN:
                key = event.key.keysym.sym
                if event.key.repeat or key in self.held_keys:
                    continue
                self.held_keys.add(key)
                if key == s.SDLK_r:
                    full = bool(self.held_keys & {s.SDLK_LSHIFT, s.SDLK_RSHIFT}) or self.complete
                    self.restart(full=full)
                    break
                if key == s.SDLK_RETURN:
                    if self.complete:
                        self.restart(full=True)
                        break
                    self.paused = False
                elif key == s.SDLK_p and not self.complete:
                    self.paused = not self.paused
                    self.held_keys.clear()
                    self._clear_absorb_input()
                elif self.paused or self.complete or self.player.state == 'DEAD':
                    continue
                elif key in (s.SDLK_SPACE, s.SDLK_z):
                    self._clear_absorb_input()
                    self.player.jump()
                elif key in (s.SDLK_x, s.SDLK_LSHIFT, s.SDLK_RSHIFT):
                    if self.player.state == 'DASH' and self.player.dash_left > 0:
                        self._absorb_input_left = MOVEMENT['absorb_input_buffer']
                        self._absorb_direction = self.axes()
                        if not self.try_absorb() and self.player.grounded:
                            self.player.dash(*self.axes())
                    else:
                        self._clear_absorb_input()
                        self.player.dash(*self.axes())

    def try_absorb(self):
        if (self.player.state != 'DASH' or self.player.dash_left <= 0
                or any(self.player.body.overlaps(area) for area in self.hazards)):
            return False
        for source in self.sources:
            recent = self._absorb_contacts.get(source)
            body = self.player.body
            if not source.area.overlaps(body) and recent is not None:
                body = recent[1]
            if source.try_absorb(body):
                direction = self._absorb_direction if self._absorb_input_left > 0 else self.axes()
                self._clear_absorb_input()
                self.player.redirect_dash(*direction)
                self.player.increase_speed_level()
                if self.view is not None:
                    self.view.player.play_absorb_effect()
                return True
        return False

    def _update_absorb_contacts(self, dt, dash_duration):
        """대시의 실제 이동 구간을 기억해 빠르게 지나친 직후의 재입력도 받는다."""
        self._absorb_contacts = {
            source: (left - dt, body) for source, (left, body) in self._absorb_contacts.items()
            if left > dt and not source.consumed
        }
        if self.player.state != 'DASH' or self.player.dash_left <= 0:
            self._clear_absorb_input()
            return
        grace = MOVEMENT['absorb_contact_grace']
        for source in self.sources:
            if source.consumed:
                continue
            for box, dx, dy, offset, duration in self.player.movement_paths:
                if offset >= dash_duration:
                    continue
                ratio = min(1.0, (dash_duration - offset) / duration) if duration else 1.0
                dx, dy = dx * ratio, dy * ratio
                hit = first_contact_time(box, dx, dy, (source.area,))
                if hit is None or hit >= 1:
                    continue
                # 경계 접촉 대신 실제로 영역에 들어간 몸체 위치를 기억한다.
                hit = min(1.0, hit + 1e-7)
                touched = AABB(box.left + dx * hit, box.bottom + dy * hit, box.width, box.height)
                left = grace - max(0.0, dt - offset - duration * ratio * hit)
                if left > 0 and source.area.overlaps(touched):
                    self._absorb_contacts[source] = (left, touched)
            if source.area.overlaps(self.player.body):
                self._absorb_contacts[source] = (grace, self.player.body)

    def update(self, dt):
        if self.paused or self.complete:
            return
        # 마지막 대시 틱 안에서 닿았다면 대시 종료 전에 보류 입력을 판정한다.
        # 틱 끝의 상태만 보면 실제 접촉까지 끝난 대시로 취급해 놓칠 수 있다.
        if (self._absorb_input_left > 0 and self.player.state == 'DASH'
                and 0 < self.player.dash_left <= dt):
            remaining = self.player.dash_left
            hit = first_contact_time(
                self.player.body, self.player.dash_vx * remaining,
                self.player.dash_vy * remaining,
                (source.area for source in self.sources if not source.consumed),
            )
            if hit is not None and hit < 1:
                contact_dt = remaining * (hit + (1 - hit) * 1e-6)
                if 0 < contact_dt < remaining:
                    self.update(contact_dt)
                    self.update(dt - contact_dt)
                    return
        self.elapsed += dt
        self.checkpoint_flash = max(0.0, self.checkpoint_flash - dt)
        for platform in self.moving:
            platform.update(dt)
        for platform in self.disappearing:
            platform.update(dt, self.player.body)
        self.player.set_move_direction(self.axes()[0])
        dash_duration = min(dt, self.player.dash_left) if self.player.state == 'DASH' else 0.0
        self._absorb_input_left = max(0.0, self._absorb_input_left - dt)
        self.player.update(dt, self.solids, one_way=self.active_one_way,
                           hazards=self.hazards, death_y=-32, moving_platforms=self.moving)
        self._update_absorb_contacts(dt, dash_duration)
        if self._absorb_input_left > 0:
            self.try_absorb()
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
            self.held_keys.clear()
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
                self.held_keys.clear()
                self.player.set_move_direction(0)
        direction = self.player.dash_vx if self.player.state == 'DASH' else self.player.move_direction
        self.camera.follow(self.player.x, self.player.y + self.player.body_height / 2, direction, dt)

    def draw(self):
        self.view.draw()

    def close(self):
        if self.view is not None:
            self.view.close()
            self.view = None
