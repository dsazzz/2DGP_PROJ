"""흡수 성공 때만 재생하는 Python 별 부스트. 기본 상태에서는 그리지 않는다.

압축·섬광·잔광은 pixelfx collect-burst / Sprite Fusion pickup의 기법을 참고했다.
https://www.spritefusion.com/pixel-art-vfx/pickup — MIT, Copyright (c) 2026 Hugo Duprez.
라이선스와 출처는 이 폴더의 LICENSE·NOTICE.md에 보존한다.
"""
import math

from .painter import TAU, clamp, fit, rand


DURATION = 1.4
RELEASE_TIME = .035


def _star(p, x, y, radius, colors, alpha=1):
    if radius < .6 or alpha <= 0:
        return
    # 별의 외곽은 밝기를 부드럽게 낮춘다. 디더 점무늬로 모양을 깨뜨리지 않는다.
    pixels = {}
    for dx in range(-round(radius * .8), round(radius * .8) + 1):
        pixels[dx, 1] = 3
        pixels[dx, 0] = 5
    for dy in range(-round(radius), round(radius) + 1):
        pixels[0, dy] = 5
    core = max(1, radius * .5)
    for row in range(-math.ceil(core), math.ceil(core) + 1):
        width = max(0, radius * .35 * (1 - abs(row) / (core + .5)) ** 2)
        for dx in range(-round(width), round(width) + 1):
            pixels[dx, row] = 7
    for dx in range(-round(radius * .45), round(radius * .45) + 1):
        pixels[dx, 0] = 7
    for dy in range(-round(radius * .55), round(radius * .55) + 1):
        pixels[0, dy] = 7
    for (dx, dy), tone in pixels.items():
        p.blend(math.floor(x) + dx, math.floor(y) + dy, colors[tone], alpha)
    p.glow(x, y, radius * 2.8, colors[4], alpha * .22)


def absorb_boost(p, t, o):
    """발 기준 좌표. 오른쪽을 향한 별 분사와 짧은 성공 잔광."""
    if t < 0 or t >= DURATION:
        return
    gold, cyan = fit(o['palette']), fit(o['accent_palette'])
    stage, seed = o.get('stage', 2), o.get('seed', 149)
    cx, cy = -4, -28
    if t < RELEASE_TIME:
        u = t / RELEASE_TIME
        for i in range(6):
            angle = i / 6 * TAU + .2
            radius = 8 + 26 * (1 - u) ** 2
            x, y = cx + math.cos(angle) * radius, cy + math.sin(angle) * radius * .7
            p.line(x, y, x - math.cos(angle) * 5, y - math.sin(angle) * 4, gold[6], .65)
        p.glow(cx, cy, 16, gold[5], .2 + u * .2)
        return

    age = t - RELEASE_TIME
    punch = clamp(1 - age / .11)
    if punch:
        length = (26 + 82 * min(1, age / .025)) * punch
        p.line(cx - length, cy, cx + length * .65, cy, gold[5])
        p.line(cx - length * .45, cy, cx + length * .35, cy, gold[7])
        _star(p, cx, cy, 11 * punch, gold, punch)
        _star(p, -10, -70, 17 * punch, gold, punch)
        p.glow(cx, cy, 38, gold[5], punch * .28)
        for slope in (-.28, .24):
            p.line(cx - length, cy + length * slope, cx - 12, cy + 12 * slope,
                   gold[5])

    ring = clamp(1 - age / .24)
    if ring:
        radius = 9 + 48 * (1 - math.exp(-age * 18))
        for start in (.3, 2.5, 4.5):
            points = [(cx + math.cos(start + j * .13) * radius,
                       cy + math.sin(start + j * .13) * radius * .65) for j in range(11)]
            p.polyline(points[:max(2, math.ceil(len(points) * ring))], gold[4], 1)

    for i in range(14):
        a = age - rand(seed, i, 1) * .02
        life = .2 + rand(seed, i, 2) * .2
        if not 0 < a < life:
            continue
        angle = i / 14 * TAU + (rand(seed, i, 3) - .5) * .5
        speed = 240 + rand(seed, i, 4) * 180
        travel = (1 - math.exp(-a * 7)) / 7
        vx, vy = math.cos(angle) * speed - 80, math.sin(angle) * speed * .8 - 18
        x, y = cx + vx * travel, cy + vy * travel
        fade = clamp((life - a) / .12)
        colors = cyan if stage == 3 and i % 4 == 0 else gold
        length = (7 + rand(seed, i, 5) * 10) * (1 - a / life)
        dx, dy = math.cos(angle) * length, math.sin(angle) * length * .7
        p.line(x - dx, y - dy, x, y, colors[4], fade)
        p.line(x - dx * .5, y - dy * .5, x, y, colors[6], fade)
        p.dot(x, y, colors[7], fade)
        p.glow(x, y, 4, colors[4], fade * .2)

    for i, (sx, sy, delay) in enumerate(((-42, -62, .02), (42, -36, .06),
                                        (-18, 4, .12), (22, -84, .2),
                                        (-70, -28, .3), (-4, -94, .4))):
        a, life = age - delay, .32 + rand(seed, i, 8) * .12
        if not 0 < a < life:
            continue
        u = a / life
        size = (8 + rand(seed, i, 9) * 4) * min(1, u / .12) * (1 - u) ** .65
        x, y = sx - a * 18, sy - a * 10
        colors = cyan if stage == 3 and i % 3 == 0 else gold
        _star(p, x, y, size, colors, clamp((life - a) / .13))

    # 후속 별은 서로 다른 시점에 생기고 줄어들어 잔광을 만든다.
    fade_out = clamp((DURATION - t) / .22)
    for i in range(28):
        a = t - (.1 + i * .032 + rand(seed, i, 11) * .025)
        life = .25 + rand(seed, i, 12) * .15
        if not 0 < a < life:
            continue
        u = a / life
        x = -62 + rand(seed, i, 13) * 124 - a * 24
        y = -90 + rand(seed, i, 14) * 94 - a * 14
        if -20 < x < 26 and -56 < y < 0:
            x += -26 if x < 0 else 26
        radius = (3 + rand(seed, i, 15) * 3.5) * math.sin(math.pi * u) ** .7 * fade_out
        colors = cyan if stage == 3 and i % 3 == 0 else gold
        _star(p, x, y, radius, colors, clamp((life - a) / .1) * fade_out)


class Sparkles:
    """한 번의 성공 연출을 소유한다. 재발동은 이전 효과를 교체한다."""
    def __init__(self):
        self.effect = None
        self.flip = False

    def trigger(self, stage=2, flip=False):
        from .pico import PicoEffect
        self.close()
        self.flip = flip
        self.effect = PicoEffect('absorbBoost', stage=stage)
        self.effect.prerender()

    def update(self, dt):
        if self.effect is not None:
            self.effect.update(dt)
            if self.effect.done():
                self.close()

    def draw(self, x, y, zoom=1.0):
        if self.effect is not None:
            self.effect.draw(x, y, scale=zoom * 2, flip=self.flip, layer='front')

    def close(self):
        if self.effect is not None:
            self.effect.close()
            self.effect = None
