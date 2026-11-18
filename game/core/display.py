"""Display contract. LDtk pixels and physics remain world units at every viewport."""
LOGICAL_SIZE = (960, 540)
WINDOW_SIZE = (1920, 1080)
DEFAULT_VIEW_MODE = 'logical_960'
VIEW_SIZES = {'normal': (640, 360), 'zoom_half': (1280, 720),
              'logical_960': LOGICAL_SIZE, 'logical_1280': (1280, 720),
              'logical_1920': WINDOW_SIZE}
