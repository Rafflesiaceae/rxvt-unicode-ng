# --- VENDOR - libptytty (port of libptytty/CMakeLists.txt) --------------------

# Keep libptytty's configuration separate from the terminal's config.h.
ptytty_cdata = configuration_data()
ptytty_cdata.merge_from(cdata)
ptytty_deps = []
ptytty_prefix = '''
#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#define __EXTENSIONS__ 1
'''
if host_machine.system() == 'sunos'
  # Solaris exposes descriptor passing and utmp declarations in this namespace.
  ptytty_cdata.set('_XOPEN_SOURCE', 600)
  ptytty_prefix += '#define _XOPEN_SOURCE 600\n'
endif

# Match the header preference in ptytty.C and stop at the first available one.
foreach h : ['pty.h', 'libutil.h', 'util.h']
  have_header = cpp.has_header(h, prefix: ptytty_prefix + '#include <sys/types.h>')
  ptytty_cdata.set('HAVE_' + h.underscorify().to_upper(), have_header ? 1 : false)
  if have_header
    break
  endif
endforeach

foreach h : ['sys/ioctl.h', 'stropts.h']
  have_header = cpp.has_header(h, prefix: ptytty_prefix + '#include <sys/types.h>')
  ptytty_cdata.set('HAVE_' + h.underscorify().to_upper(), have_header ? 1 : false)
  if h == 'stropts.h' and have_header
    ptytty_cdata.set('HAVE_ISASTREAM',
      cpp.has_function('isastream', prefix: ptytty_prefix) ? 1 : false)
  endif
endforeach

unix98_pty = cpp.links(ptytty_prefix + '''
  #include <stdlib.h>
  int main () { grantpt (0); unlockpt (0); ptsname (0); }
''', name: 'Unix98 ptys')
ptytty_cdata.set('UNIX98_PTY', unix98_pty ? 1 : false)
if unix98_pty
  # Unix98 allocation prefers getpt, then posix_openpt, then a device path.
  foreach f : ['getpt', 'posix_openpt']
    have_function = cpp.has_function(f, prefix: ptytty_prefix)
    ptytty_cdata.set('HAVE_' + f.to_upper(), have_function ? 1 : false)
    if have_function
      break
    endif
  endforeach
else
  # BSD systems may provide openpty in libutil rather than libc.
  have_openpty = cpp.has_function('openpty', prefix: ptytty_prefix)
  if not have_openpty
    ptytty_util = cpp.find_library('util', required: false)
    if ptytty_util.found()
      have_openpty = cpp.has_function('openpty', dependencies: ptytty_util,
        prefix: ptytty_prefix)
      if have_openpty
        ptytty_deps += ptytty_util
      endif
    endif
  endif
  ptytty_cdata.set('HAVE_OPENPTY', have_openpty ? 1 : false)
  if not have_openpty
    have_getpty = cpp.has_function('_getpty', prefix: ptytty_prefix)
    ptytty_cdata.set('HAVE__GETPTY', have_getpty ? 1 : false)
    if not have_getpty
      # Only the legacy device-scanning allocator calls revoke.
      ptytty_cdata.set('HAVE_REVOKE',
        cpp.has_function('revoke', prefix: ptytty_prefix) ? 1 : false)
    endif
  endif
endif

# Match the privilege-dropping #if/#elif chain in proxy.C.
foreach f : ['setresuid', 'setreuid', 'setuid']
  have_function = cpp.has_function(f, prefix: ptytty_prefix)
  ptytty_cdata.set('HAVE_' + f.to_upper(), have_function ? 1 : false)
  if have_function
    break
  endif
endforeach

# Match ptytty.h: prefer utmpx except on glibc, which requires utmp.
ptytty_cdata.set('UTMP_SUPPORT', 1)
ptytty_cdata.set('WTMP_SUPPORT', 1)
ptytty_cdata.set('LASTLOG_SUPPORT', 1)
ptytty_records = ['utmpx', 'utmp']
if cpp.has_define('__GLIBC__', prefix: ptytty_prefix + '#include <sys/types.h>')
  ptytty_records = ['utmp']
endif
ptytty_log_files = []
foreach record : ptytty_records
  record_prefix = ptytty_prefix + '#include <sys/types.h>\n#include <' + record + '.h>'
  have_record = cpp.has_type('struct ' + record, prefix: record_prefix)
  ptytty_cdata.set('HAVE_STRUCT_' + record.to_upper(), have_record ? 1 : false)
  if have_record
    ptytty_cdata.set('HAVE_' + record.to_upper() + '_HOST',
      cpp.has_member('struct ' + record, 'ut_host', prefix: record_prefix) ? 1 : false)
    if record == 'utmp'
      ptytty_cdata.set('HAVE_UTMP_PID',
        cpp.has_member('struct utmp', 'ut_pid', prefix: record_prefix) ? 1 : false)
      have_lastlog_header = cpp.has_header('lastlog.h',
        prefix: ptytty_prefix + '#include <sys/types.h>')
      ptytty_cdata.set('HAVE_LASTLOG_H', have_lastlog_header ? 1 : false)
      if have_lastlog_header
        record_prefix += '\n#include <lastlog.h>'
      endif
    endif
    lastlog_type = record == 'utmp' ? 'lastlog' : 'lastlogx'
    have_lastlog = cpp.has_type('struct ' + lastlog_type, prefix: record_prefix)
    ptytty_cdata.set('HAVE_STRUCT_' + lastlog_type.to_upper(),
      have_lastlog ? 1 : false)
    if record == 'utmp'
      ptytty_cdata.set('HAVE_UPDWTMP',
        cpp.has_function('updwtmp', prefix: ptytty_prefix) ? 1 : false)
      ptytty_log_files = ['UTMP', 'WTMP', 'LASTLOG']
    else
      ptytty_cdata.set('HAVE_UPDWTMPX',
        cpp.has_function('updwtmpx', prefix: ptytty_prefix) ? 1 : false)
      if have_lastlog
        ptytty_cdata.set('HAVE_UPDLASTLOGX',
          cpp.has_function('updlastlogx', prefix: ptytty_prefix) ? 1 : false)
      endif
      ptytty_log_files = ['WTMPX', 'LASTLOGX']
    endif
    break
  endif
endforeach

# Header-provided paths take precedence; never use build-host paths for a cross build.
if not meson.is_cross_build()
  foreach entry : [
    ['UTMP', ['/var/run/utmp', '/var/adm/utmp', '/etc/utmp', '/usr/etc/utmp', '/usr/adm/utmp']],
    ['WTMP', ['/var/log/wtmp', '/var/adm/wtmp', '/etc/wtmp', '/usr/etc/wtmp', '/usr/adm/wtmp']],
    ['LASTLOG', ['/var/log/lastlog', '/var/adm/lastlog']],
    ['WTMPX', ['/var/log/wtmpx', '/var/adm/wtmpx']],
    ['LASTLOGX', ['/var/log/lastlogx', '/var/adm/lastlogx']],
  ]
    if entry[0] not in ptytty_log_files
      continue
    endif
    foreach path : entry[1]
      if fs.exists(path)
        ptytty_cdata.set_quoted('PT_' + entry[0] + '_FILE', path)
        break
      endif
    endforeach
  endforeach
endif

if not cpp.has_function('sendmsg', prefix: ptytty_prefix)
  ptytty_deps += cpp.find_library('socket')
endif
if not cpp.links(ptytty_prefix + '''
  #include <stddef.h>
  #include <sys/types.h>
  #include <sys/socket.h>
  #include <sys/uio.h>
  int main () {
    struct msghdr msg = {};
    struct iovec iov = {};
    char buf[100];
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = buf;
    msg.msg_controllen = sizeof buf;
    struct cmsghdr *cmsg = CMSG_FIRSTHDR (&msg);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN (sizeof (int));
    *(int *)CMSG_DATA (cmsg) = 5;
    return sendmsg (3, &msg, 0);
  }
''', dependencies: ptytty_deps, name: 'Unix file descriptor passing')
  error('libptytty requires Unix file descriptor passing support')
endif

# Match upstream's runtime check; a missing terminal or cross runner disables it.
if meson.can_run_host_binaries()
  tty_gid = cpp.run(ptytty_prefix + '''
    #include <grp.h>
    #include <sys/stat.h>
    #include <sys/types.h>
    #include <unistd.h>
    int main () {
      struct stat st;
      struct group *gr = getgrnam ("tty");
      char *tty = ttyname (0);
      return !(gr && tty && stat (tty, &st) == 0 && st.st_gid == gr->gr_gid);
    }
  ''', name: 'tty group ownership')
  ptytty_cdata.set('TTY_GID_SUPPORT', tty_gid.returncode() == 0 ? 1 : false)
endif

configure_file(output: 'config.h', configuration: ptytty_cdata)

# Present .cpp sources to Meson without renaming upstream files. The compiler
# tracks each included .C file so upstream edits still trigger recompilation.
ptytty_sources = []
foreach source : ['c-api', 'fdpass', 'logging', 'proxy', 'ptytty']
  ptytty_wrapper = configuration_data()
  ptytty_wrapper.set('PTYTTY_SOURCE', source)
  ptytty_sources += configure_file(
    input: 'libptytty_neo.cpp.in',
    output: 'libptytty_' + source + '.cpp',
    configuration: ptytty_wrapper,
  )
endforeach

# Select the target explicitly, independently of Meson's default_library option.
if get_option('ptytty-library') == 'static'
  ptytty_lib = static_library('ptytty', ptytty_sources,
    include_directories: include_directories('.'),
    dependencies: ptytty_deps,
  )
else
  ptytty_lib = shared_library('ptytty', ptytty_sources,
    include_directories: include_directories('.'),
    dependencies: ptytty_deps,
    link_args: supcxx_args,
    link_language: link_language,
    soversion: '0',
    install: true,
  )
endif
ptytty_dep = declare_dependency(
  link_with: ptytty_lib,
  include_directories: include_directories('libptytty/src'),
  dependencies: ptytty_deps,
)

# --- VENDOR - libev (port of libev/libev.m4, avoiding librt) ------------------

libev_headers = {}
foreach h : [
  'sys/inotify.h', 'sys/epoll.h', 'sys/event.h', 'port.h', 'poll.h',
  'sys/timerfd.h', 'sys/select.h', 'sys/eventfd.h', 'sys/signalfd.h',
  'linux/aio_abi.h', 'linux/fs.h',
]
  have_header = cpp.has_header(h)
  libev_headers += {h: have_header}
  cdata.set('HAVE_' + h.underscorify().to_upper(), have_header ? 1 : false)
endforeach

# These libev paths require both the header and the corresponding function.
foreach check : [
  ['inotify_init', 'sys/inotify.h'], ['epoll_ctl', 'sys/epoll.h'],
  ['kqueue', 'sys/event.h'], ['port_create', 'port.h'],
  ['poll', 'poll.h'], ['select', 'sys/select.h'], ['signalfd', 'sys/signalfd.h'],
]
  cdata.set('HAVE_' + check[0].to_upper(),
    libev_headers[check[1]] and cpp.has_function(check[0]) ? 1 : false)
endforeach

# eventfd can be used without sys/eventfd.h, using libev's own declarations.
foreach f : ['eventfd', 'nanosleep', 'unsetenv']
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

if libev_headers['linux/fs.h'] and libev_headers['sys/timerfd.h']
  cdata.set('HAVE_KERNEL_RWF_T',
    cpp.has_type('__kernel_rwf_t', prefix: '#include <linux/fs.h>') ? 1 : false)
endif
cdata.set('HAVE_FLOOR', cpp.has_function('floor', dependencies: libm) ? 1 : false)

# libev is embedded by src/ev_cpp.cpp and uses the terminal's generated config.h.
libev_inc = include_directories('libev')
