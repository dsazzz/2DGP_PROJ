"""Draw world-space terrain sprites; no editor formats or gameplay rules."""
import math
import pico2d as p

from game.core.rendering import draw_clip


class TerrainView:
    def __init__(self, layers):
        self.layers = []
        for layer in layers:
            chunks = {}
            padding = 0
            for tile in layer['tiles']:
                x,y,w,h = tile['rect']
                padding = max(padding,w,h)
                chunks.setdefault((math.floor(x/128),math.floor(y/128)),[]).append(tile)
            self.layers.append((layer['image'],padding,chunks))

    def draw(self, camera, images):
        view,(cx,cy) = camera.view,camera.offset
        for path,padding,chunks in self.layers:
            if path not in images:
                images[path] = p.load_image(path)
            image,alpha = images[path],1
            for row in range(math.floor((view.bottom-padding)/128),math.floor(view.top/128)+1):
                for col in range(math.floor((view.left-padding)/128),math.floor(view.right/128)+1):
                    for tile in chunks.get((col,row),()):
                        x,y,w,h = tile['rect']
                        if x >= view.right or x+w <= view.left or y >= view.top or y+h <= view.bottom:
                            continue
                        left,top,sw,sh = tile['source']
                        opacity = tile['opacity']
                        if alpha != opacity:
                            image.opacify(opacity)
                            alpha = opacity
                        draw_clip(image,left,image.h-top-sh,sw,sh,0,tile['flip'],
                                  x+w/2-cx,y+h/2-cy,w,h)
            if alpha != 1:
                image.opacify(1)
