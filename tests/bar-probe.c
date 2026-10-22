/* Observe bar geometry and presentation requests without reading pixels. */
#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <dlfcn.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

static void record (const char *format, ...)
{
  const char *path = getenv ("URXVT_BAR_TRACE");
  FILE *file = path ? fopen (path, "a") : NULL;
  if (!file) return;
  va_list args;
  va_start (args, format);
  vfprintf (file, format, args);
  va_end (args);
  fputc ('\n', file);
  fclose (file);
}

Window XCreateSimpleWindow (Display *d, Window parent, int x, int y,
                            unsigned int w, unsigned int h, unsigned int border,
                            unsigned long fg, unsigned long bg)
{
  typeof (&XCreateSimpleWindow) real = dlsym (RTLD_NEXT, "XCreateSimpleWindow");
  Window window = real (d, parent, x, y, w, h, border, fg, bg);
  record ("window %lu %lu %d %d %u %u", parent, window, x, y, w, h);
  return window;
}

Pixmap XCreatePixmap (Display *d, Drawable source, unsigned int w, unsigned int h, unsigned int depth)
{
  typeof (&XCreatePixmap) real = dlsym (RTLD_NEXT, "XCreatePixmap");
  Pixmap pixmap = real (d, source, w, h, depth);
  record ("pixmap %lu %lu %u %u", source, pixmap, w, h);
  return pixmap;
}

int XCopyArea (Display *d, Drawable source, Drawable target, GC gc,
               int sx, int sy, unsigned int w, unsigned int h, int dx, int dy)
{
  typeof (&XCopyArea) real = dlsym (RTLD_NEXT, "XCopyArea");
  record ("copy %lu %lu %d %d %u %u %d %d", source, target, sx, sy, w, h, dx, dy);
  return real (d, source, target, gc, sx, sy, w, h, dx, dy);
}

int XFillRectangle (Display *d, Drawable target, GC gc, int x, int y, unsigned int w, unsigned int h)
{
  typeof (&XFillRectangle) real = dlsym (RTLD_NEXT, "XFillRectangle");
  record ("fill %lu %d %d %u %u %lu", target, x, y, w, h, (unsigned long)gc);
  return real (d, target, gc, x, y, w, h);
}

int XSetForeground (Display *d, GC gc, unsigned long pixel)
{
  typeof (&XSetForeground) real = dlsym (RTLD_NEXT, "XSetForeground");
  record ("foreground %lu %lu", (unsigned long)gc, pixel);
  return real (d, gc, pixel);
}

int XSync (Display *d, Bool discard)
{
  typeof (&XSync) real = dlsym (RTLD_NEXT, "XSync");
  record ("sync");
  return real (d, discard);
}

Bool XQueryPointer (Display *d, Window w, Window *root, Window *child,
                    int *rx, int *ry, int *x, int *y, unsigned int *mask)
{
  typeof (&XQueryPointer) real = dlsym (RTLD_NEXT, "XQueryPointer");
  record ("query_pointer");
  return real (d, w, root, child, rx, ry, x, y, mask);
}
