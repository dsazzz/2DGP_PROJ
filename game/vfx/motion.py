"""Actual recorded sprite poses, tinted and faded like motion.js.

Samples use pico2d foot x/y, game time, top-left source rect, facing and display
size. The normalized 128px anchor convention matches the existing JS samples.
"""
from collections import OrderedDict
import numpy as np

from .effects import speed_stage
from .painter import clamp


class MotionEchoes:
    def __init__(self, image_rgba):
        image = np.asarray(image_rgba)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 4:
            raise ValueError('Expected an RGBA uint8 sprite atlas')
        self.image = image
        self._poses = OrderedDict()
        self._textures = {}

    def _pose(self, rect, stage):
        key = (stage, *rect)
        if key not in self._poses:
            x, y, w, h = rect
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > self.image.shape[1] or y + h > self.image.shape[0]:
                raise ValueError('Motion sample rectangle is outside the sprite atlas')
            pose = np.empty((h, w, 4), dtype=np.uint8)
            if stage == 3:
                y = np.arange(h) + .5
                u = (y - h * .38) / (h * .30)
                blend = np.clip((u - .32) / (.58 - .32), 0, 1)
                top, bottom = np.array((166, 239, 255)), np.array((255, 209, 109))
                rgb = np.rint(top + (bottom - top) * blend[:, None]).astype(np.uint8)
                pose[..., :3] = rgb[:, None, :]
            else:
                pose[..., :3] = (255, 209, 109)
            x, y, w, h = rect
            pose[..., 3] = self.image[y:y + h, x:x + w, 3]
            if len(self._poses) >= 24:
                old, _ = self._poses.popitem(last=False)
                texture = self._textures.pop(old, None)
                if texture is not None:
                    texture.close()
            self._poses[key] = pose
        self._poses.move_to_end(key)
        return key, self._poses[key]

    def poses(self, samples, now, *, stage=2, lifetime=.14, opacity=.16):
        """Return at most three draws, oldest first, with no invented movement."""
        stage = speed_stage(stage)
        if stage == 1:
            return []
        lifetime, opacity = clamp(lifetime, .01, .2), clamp(opacity, 0, .2)
        recent = [sample for sample in samples if 0 < now - sample['time'] < lifetime]
        recent = sorted(recent, key=lambda sample: sample['time'], reverse=True)[:3][::-1]
        draws = []
        for sample in recent:
            rect = tuple(sample['rect'])
            key, pose = self._pose(rect, stage)
            age = (now - sample['time']) / lifetime
            draws.append({**sample, 'key': key, 'rgba': pose, 'size': sample.get('size', 128),
                          'anchor': sample.get('anchor', (66, 89)), 'opacity': opacity * (1 - age) ** 2})
        return draws

    def draw(self, samples, now, *, stage=2, lifetime=.14, opacity=.16, offset=(0, 0)):
        from .pico import StreamingTexture
        left, bottom = offset
        for sample in self.poses(samples, now, stage=stage, lifetime=lifetime, opacity=opacity):
            key, rgba = sample['key'], sample['rgba']
            if key not in self._textures:
                texture = StreamingTexture()
                texture.upload(rgba)
                self._textures[key] = texture
            texture = self._textures[key]
            w, h = rgba.shape[1], rgba.shape[0]
            anchor = sample['anchor']
            texture.draw(sample['x'] - left, sample['y'] - bottom, scale=sample['size'] / w,
                         origin=(anchor[0] * w / 128, anchor[1] * h / 128),
                         flip=sample.get('facing', 1) < 0, opacity=sample['opacity'])

    def close(self):
        for texture in self._textures.values():
            texture.close()
        self._textures.clear()
        self._poses.clear()
