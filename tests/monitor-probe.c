/* Supply deterministic CRTC timings while keeping real X11 event delivery. */
#define _GNU_SOURCE
#include <X11/extensions/Xrandr.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

static const char *settings (void)
{
  return getenv ("URXVT_TEST_MONITORS");
}

static double mode (int index, unsigned long *flags)
{
  double rates[2] = { 144., 60. };
  unsigned long values[2] = { 0, 0 };
  FILE *file = settings () ? fopen (settings (), "r") : NULL;
  if (file)
    {
      if (fscanf (file, "%lf %lu %lf %lu", &rates[0], &values[0], &rates[1], &values[1]) != 4)
        abort ();
      fclose (file);
    }
  *flags = values[index];
  return rates[index];
}

Bool XRRQueryExtension (Display *display, int *event, int *error)
{
  typeof (&XRRQueryExtension) real = dlsym (RTLD_NEXT, "XRRQueryExtension");
  return getenv ("URXVT_TEST_NO_RANDR") ? False : real (display, event, error);
}

static XRRScreenResources *resources (void)
{
  struct fixture {
    XRRScreenResources resources;
    RRCrtc crtcs[2];
    XRRModeInfo modes[2];
  } *fixture = calloc (1, sizeof *fixture);
  fixture->resources.ncrtc = fixture->resources.nmode = 2;
  fixture->resources.crtcs = fixture->crtcs;
  fixture->resources.modes = fixture->modes;
  for (int i = 0; i < 2; i++)
    {
      unsigned long flags;
      double rate = mode (i, &flags);
      fixture->crtcs[i] = i + 1;
      fixture->modes[i].id = i + 1;
      fixture->modes[i].width = 400;
      fixture->modes[i].height = 600;
      fixture->modes[i].hTotal = fixture->modes[i].vTotal = 1000;
      fixture->modes[i].dotClock = rate > 0. ? rate * 1000000. : 0;
      fixture->modes[i].modeFlags = flags;
    }
  return &fixture->resources;
}

XRRScreenResources *XRRGetScreenResourcesCurrent (Display *display, Window root)
{
  typeof (&XRRGetScreenResourcesCurrent) real = dlsym (RTLD_NEXT, "XRRGetScreenResourcesCurrent");
  return settings () ? resources () : real (display, root);
}

XRRScreenResources *XRRGetScreenResources (Display *display, Window root)
{
  typeof (&XRRGetScreenResources) real = dlsym (RTLD_NEXT, "XRRGetScreenResources");
  return settings () ? resources () : real (display, root);
}

void XRRFreeScreenResources (XRRScreenResources *value)
{
  typeof (&XRRFreeScreenResources) real = dlsym (RTLD_NEXT, "XRRFreeScreenResources");
  if (settings ()) free (value); else real (value);
}

XRRCrtcInfo *XRRGetCrtcInfo (Display *display, XRRScreenResources *value, RRCrtc crtc)
{
  typeof (&XRRGetCrtcInfo) real = dlsym (RTLD_NEXT, "XRRGetCrtcInfo");
  if (!settings ())
    return real (display, value, crtc);
  unsigned long flags;
  double rate = mode (crtc - 1, &flags);
  XRRCrtcInfo *info = calloc (1, sizeof *info);
  if (rate >= 0.)
    {
      info->x = (crtc - 1) * 400;
      info->width = 400;
      info->height = 600;
      info->mode = crtc;
    }
  return info;
}

void XRRFreeCrtcInfo (XRRCrtcInfo *value)
{
  typeof (&XRRFreeCrtcInfo) real = dlsym (RTLD_NEXT, "XRRFreeCrtcInfo");
  if (settings ()) free (value); else real (value);
}
