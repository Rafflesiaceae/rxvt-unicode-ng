executable(rxvtname,
  'rxvt.cpp',
  'command.cpp',
  'rxvtfont.cpp',
  'init.cpp',
  'main.cpp',
  'misc.cpp',
  'screen.cpp',
  'frame_neo.cpp',
  'prompt_neo.cpp',
  'scrollbar.cpp',
  'scrollbar-next.cpp',
  'scrollbar-rxvt.cpp',
  'scrollbar-xterm.cpp',
  'scrollbar-plain.cpp',
  'xdefaults.cpp',
  'encoding.cpp',
  'rxvttoolkit.cpp',
  'monitor_neo.cpp',
  'rxvtutil.cpp',
  'keyboard.cpp',
  'rxvtimg.cpp',
  'ev_cpp.cpp',
  'rxvtlua_neo.cpp',
  include_directories: config_inc,
  link_args: supcxx_args,
  link_language: link_language,
  dependencies: base_deps + x_deps,
  install: true,
)

# The example plugins are not active by default, they are meant to be
# copied or linked into ~/.config/urxvt/plugins.
if have_lua
  install_data('lua/keyboard-select.lua', 'lua/links.lua', 'lua/search.lua',
    install_dir: get_option('datadir') / 'urxvt' / 'lua')
endif
