from __future__ import annotations

import os


app_path = defines["app"]
background_path = defines["background"]
https_installer = defines["https_installer"]

files = [app_path, https_installer]
symlinks = {"Applications": "/Applications"}
badge_icon = defines["icon"]
background = background_path
format = "UDZO"
compression_level = 9
window_rect = ((120, 80), (900, 760))
icon_size = 144
text_size = 16
icon_locations = {
    os.path.basename(app_path): (214, 342),
    "Applications": (686, 342),
    os.path.basename(https_installer): (700, 610),
}
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
arrange_by = None
grid_offset = (0, 0)
grid_spacing = 100
label_pos = "bottom"
