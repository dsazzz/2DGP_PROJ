"""Python versions of game/vfx/effects/*.js; no JavaScript runtime required."""
from dataclasses import dataclass, field
import math

import numpy as np

from .painter import TAU, clamp, fit, rand


ELECTRIC = ('#151020', '#302542', '#55446d', '#81759e', '#b3a9d0', '#ded8ef', '#f2effa', '#ffffff')
WARM = ('#382039', '#67404a', '#a86648', '#e3a04d', '#ffd16d', '#ffe8ab', '#fff3d4', '#ffffff')
RED = ('#270812', '#5e0b1c', '#94142a', '#cb1d32', '#fa293d', '#ff5260', '#ff9c99', '#fff1df')
SPEED_GOLD = ('#392039', '#704039', '#b16b37', '#eaa847', '#ffd373', '#ffe7a7', '#fff1ce', '#fff9e9')
SPEED_CYAN = ('#173341', '#235361', '#398092', '#61b4c8', '#8ae3f1', '#b9f2fa', '#defaff', '#f3fdff')


def speed_stage(value=2):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        value = 2
    return max(1, min(3, math.floor(value)))


def _window(t, start, end, edge=.1):
    return min(clamp((t - start) / edge), clamp((end - t) / edge))


def gate(p, t, o):
    colors = fit(o.get('palette', ELECTRIC))
    phase, variant, seed = t % 4, o.get('variant', 0), o['seed']
    active, charge = _window(phase, 1.1, 2.65, .13), _window(phase, .35, 1.1, .15)
    if charge > 0:
        for y in range(-76, 77, 11):
            k = charge * (.25 + .35 * (1 + math.sin(y * .11 + phase * TAU * 3)) / 2)
            p.line(0, y, 0, y + 3, colors[3], k)
    if active > 0:
        tick = math.floor(phase * 24)
        strands = 3 if variant == 0 else 2 if variant == 1 else 1
        for strand in range(strands):
            points = []
            for j in range(21):
                y, envelope = -78 + j * 7.8, math.sin(j / 20 * math.pi)
                x = (rand(seed + strand * 13, tick, j) * 2 - 1) * envelope * (14 if variant == 1 else 6)
                x += (strand - (strands - 1) / 2) * (9 if variant == 0 else 5) * envelope
                if variant == 2:
                    x += math.sin(j * .8 - phase * TAU * 3) * 6 * envelope
                points.append((x, y))
            p.polyline(points, colors[3], active)
            p.polyline([(x + 1, y) for x, y in points], colors[5], active)
            p.polyline(points, colors[7], active)
            for j in range(2, len(points) - 2, 4):
                x, y = points[j]
                direction = 1 if (j + strand) % 2 else -1
                p.line(x, y, x + direction * (4 + rand(j, tick) * 6), y + 4, colors[4], active * .6)
                p.glow(x, y, 9, colors[3], active * .13)
        if variant == 0:
            for j in range(4):
                y = -60 + j * 40 + math.sin(phase * TAU + j) * 5
                p.line(-9, y, 9, y + 4, colors[4], active * .3)
        if variant == 2:
            y = -76 + ((phase * 1.5) % 1) * 152
            p.line(-17, y, 17, y, colors[6], active * .75)
            p.glow_line(-17, y, 17, y, 5, colors[3], active * .2)
    for y in (-78, 78):
        k = max(active, charge * .22)
        if k > 0:
            p.circle(0, y, 1.8, colors[6], k)
            p.glow(0, y, 13, colors[4], k * .3)


def dash(p, t, o):
    u = t / .52
    if t <= 0 or u >= 1:
        return
    colors, seed, alpha = fit(o.get('palette', WARM)), o['seed'], (1 - u) ** 1.6
    for j in range(24):
        age = t - rand(seed, j, 1) * .07
        if age <= 0:
            continue
        x = -12 - age * (70 + rand(seed, j, 2) * 125)
        y = (rand(seed, j, 3) - .5) * (8 + u * 20)
        length = (4 + rand(j, seed, 4) * 12) * (1 - u * .5)
        p.line(x, y, x - length, y, colors[j % 3 + 3], alpha)
        if j % 4 == 0:
            p.px(x, y, colors[6])
            p.glow(x, y, 5, colors[3], alpha * .15)
    p.glow_line(-35, 0, -7, 0, 9, colors[3], alpha * .12)
    if t < .09:
        p.line(-23, -1, -4, -1, colors[6], 1 - t / .09)


def contact(p, t, o):
    wall, seed = o.get('wall', False), o['seed']
    u = t / (.42 if wall else .55)
    if t <= 0 or u >= 1:
        return
    colors, k = fit(o.get('palette', WARM)), (1 - u) ** 1.8
    for j in range(20):
        angle, speed = -math.pi + rand(seed, j, 1) * math.pi, 20 + rand(seed, j, 2) * 48
        x, y = math.cos(angle) * speed * t, math.sin(angle) * speed * t + 65 * t * t
        if wall:
            x, y = y, x
        p.line(x, y, x - math.cos(angle) * 2, y - math.sin(angle) * 2, colors[3 + j % 4], k)
        if j % 5 == 0:
            p.glow(x, y, 5, colors[3], k * .15)
    if not wall:
        if t < .08:
            p.line(-5, 0, 5, 0, colors[6], 1 - t / .08)
        p.ellipse(0, 0, 3 + u * 29, 1 + u * 3, colors[3], k * .27)
        p.glow(0, -1, 12, colors[4], k * .2)


def bob_at(t):
    return math.sin(TAU * (t % 2.4) / 2.4) * 1.5


def light(p, t, o):
    colors, size = fit(o.get('palette', RED)), o.get('size', 1)
    phase, cy, glow = (t % 2.4) / 2.4, bob_at(t) * size, o.get('glow', 1)
    previous_fade = p.fade
    p.fade *= clamp(o.get('opacity', 1))
    pulse = .5 + .5 * math.cos(TAU * phase)
    breath = .97 + .06 * pulse
    p.glow(0, cy, 38 * size, colors[3], .32 * glow)
    p.glow(0, cy, 25 * size, colors[4], (.32 + .04 * pulse) * glow)
    for radius, tone, opacity in ((18, 3, .55), (14, 4, .60), (10, 4, .65), (7, 5, .4)):
        p.disc(0, cy, radius * size * breath, colors[tone],
               lambda d, angle, opacity=opacity: opacity * np.maximum(0, 1 - d * d) ** 1.4)
    dx, dy = (-1.6 + math.cos(TAU * phase) * .7) * size, (-1.6 + math.sin(TAU * phase) * .7) * size
    p.glow(dx, cy + dy, 12 * size, colors[4], .22 * glow)
    p.disc(dx, cy + dy, 4 * size, colors[5], lambda d, angle: .26 * (1 - d * d) ** 2)
    p.glow(-4 * size, cy - 3 * size, 8 * size, colors[5], .12 * glow)
    p.fade = previous_fade


def small_source(p, t, o):
    light(p, t, {'size': .55, **o})


def absorb(p, t, o):
    if t < 0 or t >= .9:
        return
    colors, seed = fit(o.get('palette', RED)), o['seed']
    tx, ty = clamp(o.get('target_x', -56) / 64, -1, 1) * 64, clamp(o.get('target_y', 10) / 40, -1, 1) * 40
    cy = bob_at(o.get('idle_phase', 0))
    if t < .30:
        q = t / .30
        light(p, o.get('idle_phase', 0), {**o, 'size': o.get('size', 1) * (1 - .92 * q * q),
                                        'opacity': 1 - q * q, 'glow': 1})
    for i in range(24):
        delay, lifetime = .035 + rand(seed, i, 1) * .12, .36 + rand(seed, i, 2) * .22
        u = clamp((t - delay) / lifetime)
        if t <= delay or u >= 1:
            continue
        angle, radius = rand(seed, i, 3) * TAU, 4 + rand(seed, i, 4) * 13
        sx, sy = math.cos(angle) * radius, cy + math.sin(angle) * radius * .7

        def point(v):
            arc = math.sin(math.pi * v) * (-1 if i % 2 else 1) * (5 + rand(seed, i, 5) * 9)
            return sx + (tx - sx) * v * v, sy + (ty - sy) * v * v + arc

        x, y = point(u)
        lx, ly = point(max(0, u - .13))
        alpha = math.sin(math.pi * u) ** .6
        p.line(lx, ly, x, y, colors[3], 1)
        p.dot(x, y, colors[i % 3 + 5], alpha)
        p.glow_line(lx, ly, x, y, 3, colors[4], alpha * .1)
    arrival = max(0, 1 - abs(t - .62) / .16)
    if arrival > 0:
        p.disc(tx, ty, 1.4, colors[7], arrival)
        p.glow(tx, ty, 12, colors[5], arrival * .4)


def laser(p, t, o):
    colors, phase = fit(o.get('palette', ELECTRIC)), t % 3.2
    active, charge = _window(phase, 1.05, 1.9, .06), _window(phase, .2, 1.05, .1)
    if charge > 0:
        for x in range(0, 154, 10):
            p.line(x, 0, x + 3, 0, colors[4], charge * .6)
    if active > 0:
        p.beam(0, 0, 152, 0, 3, colors[3], active)
        p.line(0, 0, 152, 0, colors[7], active)
        p.glow_line(0, 0, 152, 0, 7, colors[4], active * .25)
        for j in range(8):
            age = (phase + j * .07) % .5
            x, y = 152 - age * 16, math.sin(j * 8 + phase * 40) * age * 15
            p.dot(x, y, colors[5], active * (1 - age * 2))
        p.glow(0, 0, 11, colors[5], active * .4)


def _streak(p, x, y, length, dy, color, alpha, width=1, body=False):
    steps = math.ceil(abs(length))
    for j in range(steps + 1):
        u = j / steps
        fade = alpha * (1 - u * .7) if body else alpha * (1 - u) ** .7
        p.blend(x - u * length, y - u * dy, color, fade)
        if not body and width > 1 and u < .65:
            p.blend(x - u * length, y - u * dy + 1, color, fade * .55)


def speed_streaks(p, phase, o, power=1, burst=False):
    stage = speed_stage(o.get('stage', 2))
    strength = clamp(o.get('strength', 1)) * power
    if stage == 1 or strength <= 0:
        return
    gold, cyan, seed = fit(o.get('palette', SPEED_GOLD)), fit(SPEED_CYAN), o.get('seed', 91)

    def palette(i):
        return cyan if stage == 3 and i % 5 < 3 else gold

    for i in range(20 if stage == 3 else 16):
        u = (phase + rand(seed, i, 1)) % 1
        k = math.sin(math.pi * u) ** 2 * strength
        x, y = 42 - u * (155 + rand(seed, i, 2) * 35), -75 + rand(seed, i, 3) * 65
        length, colors = (5 + rand(seed, i, 4) * 13) * (1.3 if burst else 1), palette(i)
        _streak(p, x, y, -length, 0, colors[5 + i % 2], k * .95, body=True)
        if i % 3 == 0:
            p.glow(x, y, 3, colors[4], k * .12)
    if o.get('grounded', True) is False:
        return
    for i in range(20 if stage == 3 else 15):
        u = (phase * 2 + rand(seed, i, 11)) % 1
        k = math.sin(math.pi * u) ** .9 * strength
        emitter = (-36, -16, 8)[i % 3] + rand(seed, i, 12) * 8
        x = emitter - u * (55 + rand(seed, i, 13) * 65)
        y = -6 - rand(seed, i, 15) * 2 + u * 2
        length, colors = 4 + rand(seed, i, 14) * (11 if burst else 8), palette(i + 1)
        _streak(p, x, y, -length, .3, colors[4 + i % 2], k, 2 if i % 4 == 0 else 1)
        p.blend(x, y, colors[6], k * .9)
        p.glow(x, y, 3, colors[4], k * .22)


def speed_trail(p, t, o):
    speed_streaks(p, (t % .8) / .8, o)


def dash_trail(p, t, o):
    if t <= 0 or t >= .38:
        return
    power = clamp(t / .025) * (1 - clamp((t - .07) / .31)) ** 1.4
    speed_streaks(p, t / .38, o, power, True)


@dataclass(frozen=True)
class EffectSpec:
    size: tuple
    origin: tuple
    duration: float
    loop: bool
    fps: int
    draw: object
    defaults: dict = field(default_factory=dict)
    layer: str = 'front'


# Names match the approved JS registry. Keyword options use Python snake_case.
EFFECTS = {
    'electricLattice': EffectSpec((112, 208), (56, 104), 4, True, 30, gate,
                                 {'palette': ELECTRIC, 'seed': 31, 'variant': 0}),
    'electricTendrils': EffectSpec((112, 208), (56, 104), 4, True, 30, gate,
                                  {'palette': ELECTRIC, 'seed': 31, 'variant': 1}),
    'electricScan': EffectSpec((112, 208), (56, 104), 4, True, 30, gate,
                              {'palette': ELECTRIC, 'seed': 31, 'variant': 2}),
    'dash': EffectSpec((176, 88), (140, 44), .52, False, 60, dash, {'palette': WARM, 'seed': 41}),
    'landing': EffectSpec((112, 88), (56, 55), .55, False, 60, contact, {'palette': WARM, 'seed': 53}),
    'wall': EffectSpec((96, 112), (40, 56), .42, False, 60, contact,
                       {'palette': WARM, 'seed': 53, 'wall': True}),
    'absorb': EffectSpec((136, 128), (68, 64), .9, False, 60, absorb,
                         {'palette': RED, 'seed': 71, 'target_x': -36, 'target_y': 8}),
    'source': EffectSpec((192, 160), (96, 80), 2.4, True, 30, light,
                         {'palette': RED, 'seed': 21, 'glow': 1}),
    'smallSource': EffectSpec((64, 64), (32, 32), 2.4, True, 30, small_source,
                              {'palette': RED, 'seed': 71}),
    'lightAbsorb': EffectSpec((192, 160), (96, 80), .9, False, 30, absorb,
                              {'palette': RED, 'seed': 21, 'idle_phase': 0, 'target_x': -56, 'target_y': 10}),
    'laser': EffectSpec((196, 72), (20, 36), 3.2, True, 30, laser,
                        {'palette': ELECTRIC, 'seed': 83}),
    'speedTrail': EffectSpec((288, 160), (208, 112), .8, True, 60, speed_trail,
                             {'stage': 2, 'grounded': True, 'strength': .85, 'seed': 91}, 'back'),
    'dashTrail': EffectSpec((288, 160), (208, 112), .38, False, 60, dash_trail,
                            {'stage': 2, 'grounded': True, 'strength': 1, 'seed': 97}, 'back'),
}
EFFECTS['shatter'] = EFFECTS['lightAbsorb']
