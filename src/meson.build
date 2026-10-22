# Binaries of rxvt-unicode, a port of src/Makefile.in.
#
# The perl glue (rxvtperl.xs, urxvt.pm and the extensions in perl/) is left
# out, the meson build does not support the embedded perl interpreter. The
# lua plugin system (rxvtlua_neo.cpp, example plugins in lua/) replaces it.

# Objects shared between urxvt and the urxvtd daemon.
common = static_library('rxvt-common',
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
  dependencies: base_deps + x_deps,
)

executable(rxvtname, 'rxvt.cpp',
  include_directories: config_inc,
  link_with: common,
  link_args: supcxx_args,
  link_language: link_language,
  dependencies: base_deps + x_deps,
  install: true,
)

# The daemon and its client are optional (-Ddaemon=false).
if get_option('daemon')
  executable(rxvtname + 'd', 'rxvtd.cpp', 'rxvtdaemon.cpp',
    include_directories: config_inc,
    link_with: common,
    link_args: supcxx_args,
    link_language: link_language,
    dependencies: base_deps + x_deps,
    install: true,
  )

  # The client only talks to the daemon over a socket, so it needs no X.
  executable(rxvtname + 'c', 'rxvtc.cpp', 'rxvtdaemon.cpp',
    include_directories: config_inc,
    link_args: supcxx_args,
    link_language: link_language,
    dependencies: base_deps,
    install: true,
  )
endif

# urclock is an unrelated analog clock, it is optional (-Durclock=true).
if get_option('urclock')
  executable('urclock', 'rclock.cpp',
    include_directories: config_inc,
    link_args: supcxx_args,
    link_language: link_language,
    dependencies: base_deps + x_deps,
    install: true,
  )
endif

# The example plugins are not active by default, they are meant to be
# copied or linked into ~/.config/urxvt/plugins.
if have_lua
  install_data('lua/keyboard-select.lua', 'lua/links.lua', 'lua/search.lua',
    install_dir: get_option('datadir') / 'urxvt' / 'lua')
endif
