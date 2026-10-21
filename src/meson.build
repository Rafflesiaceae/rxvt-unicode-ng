# Binaries of rxvt-unicode, a port of src/Makefile.in.
#
# The perl glue (rxvtperl.xs, urxvt.pm and the extensions in perl/) is left
# out, the meson build does not support the embedded perl interpreter. The
# lua plugin system (rxvtlua_neo.C, example plugins in lua/) replaces it.

# Objects shared between urxvt and the urxvtd daemon.
common = static_library('rxvt-common',
  'command.C',
  'rxvtfont.C',
  'init.C',
  'main.C',
  'misc.C',
  'screen.C',
  'prompt_neo.C',
  'scrollbar.C',
  'scrollbar-next.C',
  'scrollbar-rxvt.C',
  'scrollbar-xterm.C',
  'scrollbar-plain.C',
  'xdefaults.C',
  'encoding.C',
  'rxvttoolkit.C',
  'rxvtutil.C',
  'keyboard.C',
  'rxvtimg.C',
  'ev_cpp.C',
  'rxvtlua_neo.C',
  include_directories: config_inc,
  dependencies: base_deps + x_deps,
)

executable(rxvtname, 'rxvt.C',
  include_directories: config_inc,
  link_with: common,
  link_args: supcxx_args,
  link_language: link_language,
  dependencies: base_deps + x_deps,
  install: true,
)

executable(rxvtname + 'd', 'rxvtd.C', 'rxvtdaemon.C',
  include_directories: config_inc,
  link_with: common,
  link_args: supcxx_args,
  link_language: link_language,
  dependencies: base_deps + x_deps,
  install: true,
)

# The client only talks to the daemon over a socket, so it needs no X.
executable(rxvtname + 'c', 'rxvtc.C', 'rxvtdaemon.C',
  include_directories: config_inc,
  link_args: supcxx_args,
  link_language: link_language,
  dependencies: base_deps,
  install: true,
)

executable('urclock', 'rclock.C',
  include_directories: config_inc,
  link_args: supcxx_args,
  link_language: link_language,
  dependencies: base_deps + x_deps,
  install: true,
)

# The example plugins are not active by default, they are meant to be
# copied or linked into ~/.config/urxvt/plugins.
if luajit_dep.found()
  install_data('lua/links.lua', 'lua/search.lua',
    install_dir: get_option('datadir') / 'urxvt' / 'lua')
endif
