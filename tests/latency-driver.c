/* Measure the first X server window update without capturing screen pixels. */
#define _POSIX_C_SOURCE 200809L
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/keysym.h>
#include <X11/extensions/Xdamage.h>
#include <X11/extensions/XTest.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>

static double now (void)
{
  struct timespec value;
  clock_gettime (CLOCK_MONOTONIC, &value);
  return value.tv_sec + value.tv_nsec * 1e-9;
}

static void pause_for (double seconds)
{
  if (seconds > 0.)
    {
      struct timespec delay = { (time_t)seconds,
        (long)((seconds - (time_t)seconds) * 1e9) };
      while (nanosleep (&delay, &delay) && errno == EINTR)
        ;
    }
}

static void output (int fd, const char *data)
{
  size_t length = strlen (data);
  while (length)
    {
      ssize_t count = write (fd, data, length);
      if (count < 0 && errno == EINTR)
        continue;
      if (count <= 0)
        {
          perror ("PTY write");
          exit (1);
        }
      data += count;
      length -= count;
    }
}

static Window terminal_window (Display *display, unsigned long pid)
{
  Window root, parent, *children = NULL, result = None;
  unsigned int count;
  Atom property = XInternAtom (display, "_NET_WM_PID", False);
  if (!XQueryTree (display, DefaultRootWindow (display), &root, &parent, &children, &count))
    return None;

  for (unsigned int i = 0; i < count; ++i)
    {
      Atom type;
      int format;
      unsigned long items, remaining;
      unsigned char *data = NULL;
      if (XGetWindowProperty (display, children[i], property, 0, 1, False,
                              XA_CARDINAL, &type, &format, &items, &remaining, &data) == Success
          && type == XA_CARDINAL && format == 32 && items == 1
          && *(unsigned long *)data == pid)
        result = children[i];
      if (data)
        XFree (data);
    }
  if (children)
    XFree (children);
  return result;
}

static Window text_window (Display *display, Window terminal)
{
  Window root, parent, *children = NULL, result = None;
  unsigned int count;
  unsigned long largest = 0;
  if (!XQueryTree (display, terminal, &root, &parent, &children, &count))
    return None;

  // With the scrollbar disabled, the largest visible child is the text area.
  for (unsigned int i = 0; i < count; ++i)
    {
      XWindowAttributes attributes;
      if (XGetWindowAttributes (display, children[i], &attributes)
          && attributes.map_state == IsViewable
          && (unsigned long)attributes.width * attributes.height > largest)
        {
          largest = (unsigned long)attributes.width * attributes.height;
          result = children[i];
        }
    }
  if (children)
    XFree (children);
  return result;
}

static double sample (Display *display, Damage damage, int event_base,
                      int slave, unsigned int key, const char *mode,
                      int index, double gap)
{
  // Clear accumulated damage and old events before establishing the start time.
  XDamageSubtract (display, damage, None, None);
  XSync (display, False);
  while (XPending (display))
    {
      XEvent event;
      XNextEvent (display, &event);
    }

  char text[80];
  snprintf (text, sizeof text, "\rupdate %08d", index);
  int synchronized = !strcmp (mode, "synchronized");
  int watchdog = !strcmp (mode, "watchdog");
  int ended = !synchronized;
  double limit = 2. + (synchronized ? gap : 0.);
  double start = now (), first = -1.;
  if (!strcmp (mode, "key"))
    {
      XTestFakeKeyEvent (display, key, True, 0);
      XTestFakeKeyEvent (display, key, False, 0);
      XFlush (display);
    }
  else
    {
      if (synchronized || watchdog)
        output (slave, "\033[?2026h");
      output (slave, text);
    }

  for (;;)
    {
      // Observe early damage even if the simulated application has not sent its
      // end marker yet. Sleeping for the gap would overestimate disabled sync.
      if (!ended && now () >= start + gap)
        {
          output (slave, "\033[?2026l");
          ended = 1;
        }
      while (XPending (display))
        {
          XEvent event;
          XNextEvent (display, &event);
          if (event.type == event_base + XDamageNotify && first < 0.)
            first = now () - start;
        }
      if (first >= 0. && ended)
        break;
      if (now () - start > limit)
        {
          fprintf (stderr, "Timed out waiting for update (%s sample %d)\n", mode, index);
          exit (1);
        }

      double wait = limit - (now () - start);
      if (!ended && start + gap - now () < wait)
        wait = start + gap - now ();
      if (wait < 0.)
        wait = 0.;
      struct timeval timeout = { (time_t)wait, (suseconds_t)((wait - (time_t)wait) * 1e6) };
      fd_set readable;
      FD_ZERO (&readable);
      FD_SET (ConnectionNumber (display), &readable);
      if (select (ConnectionNumber (display) + 1, &readable, NULL, NULL, &timeout) < 0
          && errno != EINTR)
        {
          perror ("select");
          exit (1);
        }
    }
  if (watchdog)
    output (slave, "\033[?2026l");
  if (!strcmp (mode, "key"))
    {
      // Verify delivery and drain the PTY input queue, including in long runs.
      fd_set readable;
      FD_ZERO (&readable);
      FD_SET (slave, &readable);
      struct timeval timeout = { 2, 0 };
      char received;
      if (select (slave + 1, &readable, NULL, NULL, &timeout) <= 0
          || read (slave, &received, 1) != 1 || received != 'a')
        {
          fprintf (stderr, "The synthetic key did not arrive at the PTY\n");
          exit (1);
        }
    }
  return first * 1000.;
}

int main (int argc, char **argv)
{
  if (argc != 8)
    {
      fprintf (stderr, "usage: latency-driver PID SLAVE SAMPLES MODE INTERVAL_MS GAP_MS WARMUP\n");
      return 1;
    }
  Display *display = XOpenDisplay (NULL);
  if (!display)
    {
      fprintf (stderr, "Cannot open benchmark display\n");
      return 1;
    }
  int event_base, error_base, test_event, test_error, major, minor;
  if (!XDamageQueryExtension (display, &event_base, &error_base)
      || !XTestQueryExtension (display, &test_event, &test_error, &major, &minor))
    {
      fprintf (stderr, "The benchmark requires XDamage and XTEST\n");
      return 1;
    }

  Window parent = None, text = None;
  double deadline = now () + 2.;
  while (!text && now () < deadline)
    {
      parent = terminal_window (display, strtoul (argv[1], NULL, 10));
      if (parent)
        text = text_window (display, parent);
      if (!text)
        pause_for (0.005);
    }
  if (!text)
    {
      fprintf (stderr, "Cannot find mapped terminal text window\n");
      return 1;
    }

  XWindowAttributes geometry;
  XGetWindowAttributes (display, text, &geometry);
  fprintf (stderr, "Text area: %dx%d pixels\n", geometry.width, geometry.height);
  XSetInputFocus (display, parent, RevertToParent, CurrentTime);
  XSync (display, False);
  pause_for (0.1);
  Damage damage = XDamageCreate (display, text, XDamageReportNonEmpty);
  unsigned int key = XKeysymToKeycode (display, XK_a);
  if (!key)
    {
      fprintf (stderr, "No keycode for the test key\n");
      return 1;
    }
  int warmup = atoi (argv[7]), samples = atoi (argv[3]);
  double interval = atof (argv[5]) / 1000.;
  for (int i = 0; i < warmup + samples; ++i)
    {
      double milliseconds = sample (display, damage, event_base, atoi (argv[2]),
                                     key, argv[4], i, atof (argv[6]) / 1000.);
      if (i >= warmup)
        printf ("%.6f\n", milliseconds);
      pause_for (interval);
    }
  XDamageDestroy (display, damage);
  XCloseDisplay (display);
  return 0;
}
