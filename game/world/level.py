"""LDtk 1.5 프로젝트를 게임 배치 데이터로 읽는다. 에디터 좌표 해석은 여기서만 한다."""
import json
from pathlib import Path

from game.core.collision import AABB
from game.objects.models import connect_electric
from game.core.paths import ART_ROOT


def entity_bounds(entity, level_height, offset=(0, 0), definition=None):
    """LDtk pivot and layer offset -> bottom-left visual rectangle, once."""
    definition = definition or {}
    px, py = entity.get('__pivot', (definition.get('pivotX', 0), definition.get('pivotY', 0)))
    w, h = entity['width'], entity['height']
    x, y = entity['px']
    return [x + offset[0] - w*px, level_height - y - offset[1] - h*(1-py), w, h]


def _anchor(visual, frame):
    """World position of the artwork's anchor, independent of editor pivot."""
    x, y, w, h = visual['rect']
    _, _, sw, sh = visual['source']
    ax, ay = frame['anchor_px']
    return [x + ax*w/sw, y + h - ay*h/sh]


def _fields(entity):
    return {field['__identifier']: field['__value'] for field in entity.get('fieldInstances', ())
            if field.get('__value') is not None}


def _rectangles(values, columns, rows, cell):
    """같은 가로 구간을 세로로 합쳐 IntGrid 내부의 불필요한 충돌 경계를 없앤다."""
    active, result = {}, []
    for row in range(rows):
        runs, col = [], 0
        while col < columns:
            if values[row * columns + col] != 1:
                col += 1
                continue
            start = col
            while col < columns and values[row * columns + col] == 1:
                col += 1
            runs.append((start, col - start))
        current = {}
        for key in runs:
            previous = active.pop(key, None)
            current[key] = ([key[0] * cell, row * cell, key[1] * cell, cell]
                            if previous is None else previous)
            if previous is not None:
                previous[3] += cell
        result.extend(active.values())
        active = current
    return result + list(active.values())


def _electric_layer(values, columns, rows, cell, offset, level_height, solids):
    """Translate editor cells to world cells and explicit adjacency, at the boundary."""
    if len(values) != columns*rows or any(value not in (0,1) for value in values):
        raise ValueError('LDtk: Electric must contain only empty (0) and Electric (1) cells')
    ox,oy = offset
    indices, cells = {}, []
    for row in range(rows):
        for col in range(columns):
            if values[row*columns+col]:
                indices[col,row] = len(cells)
                cells.append(AABB(ox+col*cell, level_height-oy-(row+1)*cell, cell, cell))
    links = [(index,indices[key]) for (col,row),index in indices.items()
             for key in ((col+1,row),(col,row+1)) if key in indices]
    return connect_electric(cells,links,tuple(AABB(*area) for area in solids))


def _tile_layer(layer, tileset, base, height, environment):
    """Return world sprite rectangles, with no LDtk fields left for the renderer."""
    size = tileset['tileGridSize']
    ox,oy = layer.get('__pxTotalOffsetX',0),layer.get('__pxTotalOffsetY',0)
    detailed = tileset['identifier'] == 'Terrain' and size == 16
    image = (ART_ROOT/'environment'/environment['terrain_detail']['image'] if detailed
             else base/tileset['relPath'])
    result = []
    for tile in layer.get('autoLayerTiles',()) or layer.get('gridTiles',()):
        x,y = tile['px'][0]+ox,height-tile['px'][1]-oy-size
        left,top = tile['src']
        if detailed:
            # The editor uses representative connection shapes; material is world aligned.
            column,row = left//16,top//16
            if not (0 <= column < 4 and 0 <= row < 4):
                raise ValueError('LDtk: unsupported terrain connection shape')
            patch_x,patch_y = int(x//size)%12,(-int(y//size)-1)%8
            index = (row*4+column)*96+patch_y*12+patch_x
            left,top = index%32*16,index//32*16
        flip = ('h' if tile['f']&1 else '')+('v' if tile['f']&2 else '')
        result.append({'rect':[x,y,size,size], 'source':[left,top,size,size],
                       'flip':flip, 'opacity':layer.get('__opacity',1)*tile.get('a',1)})
    return {'image':str(image.resolve()),'tiles':result}


def load_ldtk(path, identifier=None):
    path = Path(path)
    project = json.loads(path.read_text(encoding='utf-8-sig'))
    levels = list(project.get('levels', ()))
    for world in project.get('worlds', ()):
        levels.extend(world.get('levels', ()))
    level = next((item for item in levels if identifier is None or item['identifier'] == identifier), None)
    if level is None:
        raise ValueError('LDtk: playable level not found')
    if level.get('layerInstances') is None and level.get('externalRelPath'):
        level = json.loads((path.parent / level['externalRelPath']).read_text(encoding='utf-8-sig'))
    width, height = level['pxWid'], level['pxHei']
    data = {key: [] for key in ('floor', 'platforms', 'one_way', 'sources', 'moving',
                                'disappearing', 'jump_platforms', 'checkpoints', 'sections', 'tile_layers', 'electric')}
    data.update(size=[width, height])
    tilesets = {item['uid']: item for item in project['defs']['tilesets']}
    definitions = {item['identifier']: item for item in project['defs']['entities']}
    environment = json.loads((ART_ROOT / 'environment/environment.json').read_text(encoding='utf-8'))
    assets = {item['id']: item for item in environment['assets'] if 'rect' in item}
    data['visuals'] = {key: [] for key in ('platforms', 'one_way', 'moving', 'disappearing',
                                          'jump_platforms')}
    spawn, exit_area, checkpoints = None, None, []
    electric_layers = []
    for layer in reversed(level.get('layerInstances') or ()):
        ox, oy = layer.get('__pxTotalOffsetX', 0), layer.get('__pxTotalOffsetY', 0)
        cell = layer['__gridSize']
        if layer['__identifier'] == 'Electric' and layer['__type'] == 'IntGrid':
            electric_layers.append((layer['intGridCsv'], layer['__cWid'], layer['__cHei'], cell, (ox, oy)))
        if layer['__identifier'] == 'Collision' and layer['__type'] == 'IntGrid':
            values, columns, rows = layer['intGridCsv'], layer['__cWid'], layer['__cHei']
            if len(values) != columns * rows or any(value not in (0, 1) for value in values):
                raise ValueError('LDtk: Collision must contain only empty (0) and Solid (1) cells')
            for x, y, w, h in _rectangles(values, columns, rows, cell):
                data['floor'].append([x + ox, height - y - oy - h, w, h])
        tiles = layer.get('autoLayerTiles', ()) or layer.get('gridTiles', ())
        if tiles:
            tileset = tilesets[layer['__tilesetDefUid']]
            data['tile_layers'].append(_tile_layer(layer,tileset,path.parent,height,environment))
        for entity in layer.get('entityInstances', ()):
            kind, fields = entity['__identifier'], _fields(entity)
            definition = definitions.get(kind, {})
            box = entity_bounds(entity, height, (ox, oy), definition)
            left, bottom, ew, eh = box
            tile = entity.get('__tile') or definition.get('tileRect')
            visual = None
            if tile:
                mode = definition.get('tileRenderMode', 'Stretch')
                if mode != 'Stretch' and kind not in ('AbsorbSource', 'PlayerSpawn'):
                    raise ValueError(f'LDtk: {kind} needs Stretch tile rendering, got {mode}')
                visual = {'rect': box, 'source': [tile[k] for k in ('x', 'y', 'w', 'h')],
                          'image': str((path.parent / tilesets[tile['tilesetUid']]['relPath']).resolve())}
            x, y = left, bottom + eh
            ew, eh = entity['width'], entity['height']
            thickness = fields.get('Thickness', 8)
            # 자르기 전후 모두 아틀라스의 같은 접촉 행을 사용한다.
            frame = next((item for item in assets.values() if visual and
                          item['rect'][0] == visual['source'][0] and
                          item['rect'][1] <= visual['source'][1] < item['rect'][1] + item['rect'][3] and
                          Path(environment['atlases'][item['atlas']]['image']).name == Path(visual['image']).name), None)
            surface = 0
            if frame and 'surface_y_px' in frame:
                crop_top, crop_height = visual['source'][1], visual['source'][3]
                surface = (frame['rect'][1] + frame['surface_y_px'] - crop_top) / crop_height
            area = [left, bottom + eh*(1-surface) - thickness, ew, thickness]
            if kind == 'PlayerSpawn':
                if spawn is not None:
                    raise ValueError('LDtk: use exactly one PlayerSpawn')
                player = json.loads((ART_ROOT / 'player/player.json').read_text(encoding='utf-8-sig'))
                ax, ay = player['anchor_px']
                sw, sh = player['cell_size']
                # LDtk stores pivots to three decimals; keep feet on integer terrain.
                spawn = [round(left + ax*ew/sw), round(bottom + eh - ay*eh/sh)]
            elif kind == 'Checkpoint':
                x, y = _anchor(visual, assets['terminal'])
                checkpoints.append((fields.get('Order', 0), {
                    'spawn': [x + fields.get('RespawnOffsetX', 24), round(y)], 'terminal': [x, y],
                    'visual': visual}))
            elif kind == 'Exit':
                if exit_area is not None:
                    raise ValueError('LDtk: use exactly one Exit')
                exit_area = box
                data['exit_visual'] = visual
            elif kind == 'Platform':
                data['platforms'].append(area)
            elif kind == 'OneWay':
                data['one_way'].append(area)
            elif kind == 'MovingPlatform':
                data['moving'].append({'area': area, 'end_x': x + fields.get('Travel', 296),
                                       'speed': fields.get('Speed', 64)})
            elif kind == 'DisappearingPlatform':
                data['disappearing'].append({'area': area, 'warning_time': fields.get('WarningTime', .5),
                                             'hidden_time': fields.get('HiddenTime', 2)})
            elif kind == 'JumpPlatform':
                frame = assets['spring_rest']
                ax, ay = frame['anchor_px']
                vw, vh = frame['visible_size']
                sw, sh = visual['source'][2:]
                area = [left + (ax-vw/2)*ew/sw, bottom + eh-ay*eh/sh, vw*ew/sw, vh*eh/sh]
                data['jump_platforms'].append({'area': area,
                                              'launch_height': fields.get('LaunchHeight', 128)})
            elif kind == 'AbsorbSource':
                size = fields.get('BodySize', 28)
                data['sources'].append([left + ew/2 - size/2, bottom + eh/2 - size/2, size, size])
            elif kind == 'Hint':
                data['sections'].append({'x': x, 'hint': fields.get('Text', '')})
            visual_key = {'Platform': 'platforms', 'OneWay': 'one_way', 'MovingPlatform': 'moving',
                          'DisappearingPlatform': 'disappearing', 'JumpPlatform': 'jump_platforms'}.get(kind)
            if visual_key:
                data['visuals'][visual_key].append(visual)
    for values, columns, rows, cell, offset in electric_layers:
        data['electric'].extend(_electric_layer(values, columns, rows, cell, offset, height, data['floor']))
    if spawn is None:
        raise ValueError('LDtk: add one PlayerSpawn in an Entities layer')
    checkpoints.sort(key=lambda item: item[0])
    data['checkpoints'] = [item for _, item in checkpoints]
    if checkpoints and checkpoints[0][0] == 0:
        data['checkpoints'][0]['spawn'] = spawn
    else:
        data['checkpoints'].insert(0, {'spawn': spawn, 'terminal': None})
    data['exit'] = exit_area
    data['sections'].sort(key=lambda section: section['x'])
    return data
