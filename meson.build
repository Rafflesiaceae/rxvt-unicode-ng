# Meson build for rxvt-unicode, a port of configure.ac (which is kept
# around, so either build system can be used).

project('rxvt-unicode', 'c', 'cpp',
  meson_version: '>= 1.3',
  license: 'GPL-3.0-or-later',
  default_options: [
    # Match the flags the autoconf build defaults to (-g -O3 -fno-rtti, no
    # assertions, warnings off).
    'optimization=3',
    'debug=true',
    'b_ndebug=true',
    'cpp_rtti=false',
    'warning_level=0',
  ],
)

fs = import('fs')

# The sources include config.h as "../config.h", which resolves next to the
# sources before any include path, so a leftover config.h from an in-tree
# autoconf build would silently win over the one generated here.
if fs.exists('config.h')
  error('Found config.h of an in-tree autoconf build, run "make distclean" first.')
endif

if not fs.exists('libev/ev++.h')
  error('libev/ is missing, run "./vendor.py" to fetch the vendored copy.')
endif

# version.h is the single source of truth for the version, it holds lines
# such as '#define VERSION "9.31"'.
version = ''
date = ''
foreach line : fs.read('src/version.h').split('\n')
  if line.startswith('#define VERSION')
    version = line.split('"')[1]
  elif line.startswith('#define DATE')
    date = line.split('"')[1]
  endif
endforeach

cc = meson.get_compiler('c')
cpp = meson.get_compiler('cpp')

# All feature checks are done in C++, like configure.ac does.
cdata = configuration_data()

rxvtname = get_option('name')
prefix = get_option('prefix')
libdir = prefix / get_option('libdir')
mandir = prefix / get_option('mandir')
bindir = get_option('bindir')

# --- compiler flags ----------------------------------------------------------

add_project_arguments(
  cpp.get_supported_arguments(
    '-fvisibility-inlines-hidden',
    '-fno-threadsafe-statics',
    '-fno-enforce-eh-specs',
  ),
  language: 'cpp',
)

if get_option('warning_level') == '0'
  # Upstream builds with all warnings silenced unless asked for.
  add_project_arguments('-w', language: 'cpp')
else
  # The warnings upstream deems noise even with --enable-warnings.
  add_project_arguments(
    cpp.get_supported_arguments(
      '-Wno-parentheses',
      '-Wno-reorder',
      '-Wno-sign-compare',
      '-Wno-unused-value',
    ),
    language: 'cpp',
  )
endif

# Linking with the C compiler plus libsupc++ avoids pulling in the whole of
# libstdc++, which upstream does whenever GCC supports it.
supcxx_code = '''
struct test { };
void f () try { throw new test; } catch (...) { throw; }
int main () { return 0; }
'''
link_language = 'cpp'
supcxx_args = []
if cc.get_id() == 'gcc' and cpp.get_id() == 'gcc'
  # Linking C++ code without libstdc++ is the same as what the C compiler
  # does, and unlike that it can be checked with the C++ compiler.
  if cpp.links(supcxx_code, args: ['-nostdlib++', '-lsupc++'], name: 'working libsupc++')
    link_language = 'c'
    supcxx_args = ['-lsupc++']
  endif
endif

# AC_USE_SYSTEM_EXTENSIONS
foreach ext : [
  '_ALL_SOURCE',
  '_DARWIN_C_SOURCE',
  '__EXTENSIONS__',
  '_GNU_SOURCE',
  '_HPUX_ALT_XOPEN_SOCKET_API',
  '_NETBSD_SOURCE',
  '_OPENBSD_SOURCE',
  '_POSIX_PTHREAD_SEMANTICS',
  '__STDC_WANT_IEC_60559_ATTRIBS_EXT__',
  '__STDC_WANT_IEC_60559_BFP_EXT__',
  '__STDC_WANT_IEC_60559_DFP_EXT__',
  '__STDC_WANT_IEC_60559_FUNCS_EXT__',
  '__STDC_WANT_IEC_60559_TYPES_EXT__',
  '__STDC_WANT_LIB_EXT2__',
  '__STDC_WANT_MATH_SPEC_FUNCS__',
  '_TANDEM_SOURCE',
]
  cdata.set(ext, 1)
endforeach

# --- system libraries --------------------------------------------------------

# Libraries every binary links against.
base_deps = []

# FreeBSD needs libxpg4 for setlocale, Solaris libnsl and libsocket.
foreach check : [['setlocale', 'xpg4'], ['gethostbyname', 'nsl'], ['socket', 'socket']]
  if not cpp.has_function(check[0])
    base_deps += cpp.find_library(check[1], required: false)
  endif
endforeach

libm = cpp.find_library('m', required: false)
base_deps += libm

ptytty_dep = dependency('libptytty')
base_deps += ptytty_dep

# --- libev (port of libev/libev.m4, avoiding librt) ---------------------------

foreach h : [
  'sys/inotify.h', 'sys/epoll.h', 'sys/event.h', 'port.h', 'poll.h',
  'sys/timerfd.h', 'sys/select.h', 'sys/eventfd.h', 'sys/signalfd.h',
  'linux/aio_abi.h', 'linux/fs.h',
]
  cdata.set('HAVE_' + h.underscorify().to_upper(), cpp.has_header(h) ? 1 : false)
endforeach

foreach f : ['inotify_init', 'epoll_ctl', 'kqueue', 'port_create', 'poll', 'select',
             'eventfd', 'signalfd', 'nanosleep', 'unsetenv']
  cdata.set('HAVE_' + f.to_upper(), cpp.has_function(f) ? 1 : false)
endforeach

if cpp.has_function('clock_gettime')
  cdata.set('HAVE_CLOCK_GETTIME', 1)
elif host_machine.system() == 'linux'
  # On Linux, use the syscall wrapper rather than linking librt.
  cdata.set('HAVE_CLOCK_SYSCALL', cpp.links('''
    #include <unistd.h>
    #include <sys/syscall.h>
    #include <time.h>
    int main () { struct timespec ts; return syscall (SYS_clock_gettime, CLOCK_REALTIME, &ts); }
  ''', name: 'clock_gettime syscall') ? 1 : false)
endif

cdata.set('HAVE_KERNEL_RWF_T',
  cpp.has_type('__kernel_rwf_t', prefix: '#include <linux/fs.h>') ? 1 : false)
cdata.set('HAVE_FLOOR', cpp.has_function('floor', dependencies: libm) ? 1 : false)

# --- headers, types and functions -------------------------------------------

foreach h : ['sys/byteorder.h', 'sys/ioctl.h', 'sys/sockio.h', 'sys/strredir.h',
             'stdint.h', 'wchar.h']
  cdata.set('HAVE_' + h.underscorify().to_upper(), cpp.has_header(h) ? 1 : false)
endforeach

# Fallbacks for (very) old systems lacking these typedefs.
foreach t : [['mode_t', 'int'], ['pid_t', 'int'], ['uid_t', 'int'], ['gid_t', 'int'],
             ['int16_t', 'short'], ['uint16_t', 'unsigned short'],
             ['int32_t', 'int'], ['uint32_t', 'unsigned int']]
  if not cpp.has_type(t[0], prefix: '#include <sys/types.h>\n#include <stdint.h>')
    cdata.set(t[0], t[1])
  endif
endforeach

cdata.set('HAVE_NL_LANGINFO', cpp.links('''
  #include <langinfo.h>
  int main () { nl_langinfo (CODESET); return 0; }
''', name: 'working nl_langinfo') ? 1 : false)

# --- X11 ---------------------------------------------------------------------

x11_dep = dependency('x11')

# Every X client links these, extended by the optional libraries below.
x_deps = [x11_dep]

cdata.set('XLIB_ILLEGAL_ACCESS', cpp.compiles('''
  #define XLIB_ILLEGAL_ACCESS
  #include <X11/Xlib.h>
  void f () { Display *dpy; dpy->xdefaults = (char *)0; }
''', dependencies: x11_dep, name: 'XLIB_ILLEGAL_ACCESS') ? 1 : false)

have_xim = false
if get_option('xim')
  # Running the test is not possible when cross compiling, in which case XIM
  # stays disabled, just like with configure.
  if meson.can_run_host_binaries()
    have_xim = cpp.run('''
      #include <X11/Xlib.h>
      #include <stdlib.h>
      int main () {
        char *p;
        if ((p = XSetLocaleModifiers ("@im=none")) != NULL && *p)
          exit (XSupportsLocale () ? 0 : 1);
        else
          exit (1);
      }
    ''', dependencies: x11_dep, name: 'working Xlocale').returncode() == 0
  endif
  if have_xim
    cdata.set('USE_XIM', 1)
    cdata.set('XIMCB_PROTO_BROKEN', cpp.compiles('''
      #include <X11/Xlib.h>
      void im_destroy_cb (XIC unused1, XPointer client_data, XPointer unused3);
      void f () { XIMCallback cb; cb.callback = im_destroy_cb; }
    ''', dependencies: x11_dep, name: 'broken XIM callback',
      # Meson checks C++ code with -fpermissive, which downgrades the very
      # conversion error this test relies on to a warning.
      werror: true) ? 1 : false)
  else
    warning('xim was requested, but the locale support functions could not be found, XIM is DISABLED')
  endif
endif

cdata.set('HAVE_XSETLOCALE', cpp.links('''
  #define X_LOCALE 1
  #include <X11/Xlocale.h>
  int main () { setlocale (LC_CTYPE, ""); return 0; }
''', dependencies: x11_dep, name: 'working X setlocale') ? 1 : false)

startup_notification_dep = dependency('libstartup-notification-1.0',
  required: get_option('startup-notification'))
if startup_notification_dep.found()
  cdata.set('HAVE_STARTUP_NOTIFICATION', 1)
  x_deps += startup_notification_dep
endif

pixbuf_dep = dependency('gdk-pixbuf-2.0', required: get_option('pixbuf'))
if pixbuf_dep.found()
  cdata.set('HAVE_PIXBUF', 1)
  x_deps += pixbuf_dep
endif

if get_option('frills')
  xmu_dep = dependency('xmu', required: false)
  if xmu_dep.found()
    cdata.set('HAVE_XMU', 1)
    x_deps += xmu_dep
  endif
endif

# Xrender is needed for both Xft and the image support.
support_image = get_option('transparency') or pixbuf_dep.found()
have_xrender = false
if get_option('xft').allowed() or support_image
  xrender_dep = dependency('xrender', required: false)
  have_xrender = (xrender_dep.found()
    and cpp.has_header('X11/extensions/Xrender.h', dependencies: xrender_dep)
    and cpp.has_function('XRenderFindStandardFormat', dependencies: xrender_dep))
  if have_xrender
    x_deps += xrender_dep
  endif
endif

have_xft = false
if get_option('xft').allowed()
  if have_xrender
    xft_deps = [dependency('fontconfig', required: false), dependency('xft', required: false)]
    have_xft = (xft_deps[0].found() and xft_deps[1].found()
      and cpp.has_header('X11/Xft/Xft.h', dependencies: xft_deps)
      and cpp.has_header('fontconfig/fontconfig.h', dependencies: xft_deps)
      and cpp.has_function('XftDrawString32', dependencies: xft_deps)
      and cpp.has_function('FcPatternGet', dependencies: xft_deps))
  endif
  if have_xft
    cdata.set('XFT', 1)
    x_deps += xft_deps
  elif get_option('xft').enabled()
    error('xft was requested, but Xft/fontconfig/Xrender could not be found')
  endif
endif

if support_image and have_xrender
  support_image = cpp.compiles('''
    #include <X11/extensions/Xrender.h>
    #if RENDER_MAJOR == 0 && RENDER_MINOR <= 10
    error
    #endif
  ''', dependencies: xrender_dep, name: 'Render >= 0.11')
else
  support_image = false
endif
if support_image
  cdata.set('XRENDER', 1)
  if get_option('transparency')
    cdata.set('ENABLE_TRANSPARENCY', 1)
  endif
endif

# --- perl ------------------------------------------------------------------

# The embedded perl interpreter is deliberately not supported by the meson
# build, ENABLE_PERL is never defined. Use the autoconf build for perl.
if not get_option('resources')
  if get_option('frills')
    error('-Dresources=false requires -Dfrills=false')
  endif
  cdata.set('NO_RESOURCES', 1)
endif

# --- feature switches --------------------------------------------------------

foreach switch : [
  ['font-styles', 'ENABLE_STYLES'],
  ['iso14755', 'ISO_14755'],
  ['8bitctrls', 'EIGHT_BIT_CONTROLS'],
  ['fading', 'OFF_FOCUS_FADING'],
  ['selectionscrolling', 'SELECTION_SCROLLING'],
  ['frills', 'ENABLE_FRILLS'],
  ['mousewheel', 'MOUSE_WHEEL'],
  ['slipwheeling', 'MOUSE_SLIP_WHEELING'],
  ['rxvt-scroll', 'RXVT_SCROLLBAR'],
  ['next-scroll', 'NEXT_SCROLLBAR'],
  ['xterm-scroll', 'XTERM_SCROLLBAR'],
  ['pointer-blank', 'POINTER_BLANK'],
  ['text-blink', 'TEXT_BLINK'],
  ['unicode3', 'UNICODE_3'],
  ['combining', 'ENABLE_COMBINING'],
  ['256-color', 'USE_256_COLORS'],
  ['smart-resize', 'SMART_RESIZE'],
]
  if get_option(switch[0])
    cdata.set(switch[1], 1)
  endif
endforeach

# These are spelled the other way round, defined when the feature is off.
foreach switch : [
  ['keepscrolling', 'NO_SCROLLBAR_BUTTON_CONTINUAL_SCROLLING'],
  ['backspace-key', 'NO_BACKSPACE_KEY'],
  ['delete-key', 'NO_DELETE_KEY'],
  ['swapscreen', 'NO_SECONDARY_SCREEN'],
]
  if not get_option(switch[0])
    cdata.set(switch[1], 1)
  endif
endforeach

cdata.set('PLAIN_SCROLLBAR', 1)

# European and vietnamese codesets are always compiled in.
cdata.set('ENCODING_EU', 1)
cdata.set('ENCODING_VN', 1)
foreach codeset : get_option('codesets')
  cdata.set('ENCODING_' + codeset.to_upper(), 1)
endforeach

if get_option('fallback') != ''
  cdata.set_quoted('RESFALLBACK', get_option('fallback'))
endif
cdata.set_quoted('RESNAME', get_option('res-name'))
cdata.set_quoted('RESCLASS', get_option('res-class'))
cdata.set_quoted('RXVTNAME', rxvtname)
if get_option('term') != ''
  cdata.set_quoted('TERMENV', get_option('term'))
endif
if get_option('terminfo') != ''
  cdata.set_quoted('RXVT_TERMINFO', get_option('terminfo'))
endif

configure_file(output: 'config.h', configuration: cdata)

# Both config.h and libev/ are included via the include path by the libev
# glue (ev_cpp.h), while "../config.h" from src/ resolves via the build
# directory's src/ include path to the file generated above.
config_inc = include_directories('.', 'libev')

subdir('src')
subdir('doc')

summary({
  'version': '@0@ : @1@'.format(version, date),
  'install path': prefix / bindir,
  'linker': link_language == 'c' ? 'C compiler + libsupc++' : 'C++ compiler',
  'TERM': get_option('term') != '' ? get_option('term') : '(default)',
  'TERMINFO': get_option('terminfo') != '' ? get_option('terminfo') : '(default)',
  'resource name': get_option('res-name'),
  'resource class': get_option('res-class'),
  'resource class fallback': get_option('fallback') != '' ? get_option('fallback') : '(none)',
}, section: 'Configuration')

summary({
  'embedded perl': false,
  'image library': pixbuf_dep.found() ? 'gdk-pixbuf' : 'none',
  'xft': have_xft,
  'xim': have_xim,
}, section: 'Features', bool_yn: true)
