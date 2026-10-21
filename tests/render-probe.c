/* Observe presentation requests without capturing images or changing urxvt. */
#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static Window terminal;

static void record (const char *event, unsigned long source, unsigned long target)
{
  const char *path = getenv ("URXVT_RENDER_TRACE");
  FILE *file = path ? fopen (path, "a") : NULL;
  if (file)
    {
      struct timespec now;
      clock_gettime (CLOCK_MONOTONIC, &now);
      fprintf (file, "%s %.9f %lu %lu\n", event,
               now.tv_sec + now.tv_nsec * 1e-9, source, target);
      fclose (file);
    }
}

Window XCreateSimpleWindow (Display *d, Window parent, int x, int y,
                            unsigned int w, unsigned int h, unsigned int border,
                            unsigned long foreground, unsigned long background)
{
  typeof (&XCreateSimpleWindow) real = dlsym (RTLD_NEXT, "XCreateSimpleWindow");
  terminal = real (d, parent, x, y, w, h, border, foreground, background);
  record ("window", parent, terminal);
  return terminal;
}

int XCopyArea (Display *d, Drawable source, Drawable target, GC gc,
               int sx, int sy, unsigned int w, unsigned int h, int dx, int dy)
{
  typeof (&XCopyArea) real = dlsym (RTLD_NEXT, "XCopyArea");
  if (target == terminal)
    record ("present", source, target);
  return real (d, source, target, gc, sx, sy, w, h, dx, dy);
}

Pixmap XCreatePixmap (Display *d, Drawable source,
                       unsigned int w, unsigned int h, unsigned int depth)
{
  typeof (&XCreatePixmap) real = dlsym (RTLD_NEXT, "XCreatePixmap");
  Pixmap pixmap = real (d, source, w, h, depth);
  if (source == terminal)
    record ("frame", source, pixmap);
  return pixmap;
}

int XClearArea (Display *d, Window target, int x, int y,
                unsigned int w, unsigned int h, Bool exposures)
{
  typeof (&XClearArea) real = dlsym (RTLD_NEXT, "XClearArea");
  if (target == terminal)
    record ("clear", 0, target);
  return real (d, target, x, y, w, h, exposures);
}

int XClearWindow (Display *d, Window target)
{
  typeof (&XClearWindow) real = dlsym (RTLD_NEXT, "XClearWindow");
  if (target == terminal)
    record ("clear", 0, target);
  return real (d, target);
}

int XFillRectangle (Display *d, Drawable target, GC gc,
                    int x, int y, unsigned int w, unsigned int h)
{
  typeof (&XFillRectangle) real = dlsym (RTLD_NEXT, "XFillRectangle");
  if (target == terminal)
    record ("fill", 0, target);
  else
    record ("paint", 0, target);
  return real (d, target, gc, x, y, w, h);
}

int XDrawImageString (Display *d, Drawable target, GC gc,
                      int x, int y, const char *text, int length)
{
  typeof (&XDrawImageString) real = dlsym (RTLD_NEXT, "XDrawImageString");
  record (target == terminal ? "draw" : "paint", 0, target);
  return real (d, target, gc, x, y, text, length);
}

int XDrawImageString16 (Display *d, Drawable target, GC gc,
                        int x, int y, const XChar2b *text, int length)
{
  typeof (&XDrawImageString16) real = dlsym (RTLD_NEXT, "XDrawImageString16");
  record (target == terminal ? "draw" : "paint", 0, target);
  return real (d, target, gc, x, y, text, length);
}
