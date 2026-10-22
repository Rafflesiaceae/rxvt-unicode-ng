# Manual pages, a port of doc/Makefile.in.
#
# The *.man.in files are pregenerated from the pods and checked in, so only
# the @@...@@ placeholders need to be filled in.

sed = find_program('sed')

sed_args = [
  '-e', 's%@@RXVT_VERSION@@%' + version + '%g',
  '-e', 's%@@RXVT_NAME@@%' + rxvtname + '%g',
  '-e', 's%@@RXVT_DATE@@%' + date + '%g',
  '-e', 's%@@RXVT_LIBDIR@@%' + libdir + '%g',
  '-e', 's%@@URXVT_NAME@@%urxvt%g',
]

# [source, installed name, section]
man_pages = [
  ['rxvt.1.man.in', rxvtname, '1'],
  ['rxvt.7.man.in', rxvtname, '7'],
  ['rclock.1.man.in', 'urclock', '1'],
]
# The daemon pages are only installed together with the daemon.
if get_option('daemon')
  man_pages += [
    ['rxvtc.1.man.in', rxvtname + 'c', '1'],
    ['rxvtd.1.man.in', rxvtname + 'd', '1'],
  ]
endif

foreach page : man_pages
  custom_target(page[1] + '.' + page[2],
    input: page[0],
    output: page[1] + '.' + page[2],
    command: [sed, sed_args, '@INPUT@'],
    capture: true,
    install: true,
    install_dir: mandir / 'man' + page[2],
  )
endforeach

# Terminfo installation is disabled as a workaround for FS#79143, just like
# in doc/Makefile.in.
