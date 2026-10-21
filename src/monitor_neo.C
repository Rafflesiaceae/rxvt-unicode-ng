// Display mode discovery and automatic terminal refresh cadence.
#include "../config.h"
#include "rxvt.h"

#if HAVE_XRANDR
// Subscribe once per shared display and cache its active mode timings.
void
rxvt_display::init_monitors ()
{
  int randr_error, randr_major = 1, randr_minor = 2;
  if (XRRQueryExtension (dpy, &randr_event_base, &randr_error)
      && XRRQueryVersion (dpy, &randr_major, &randr_minor)
      && (randr_major > 1 || (randr_major == 1 && randr_minor >= 2)))
    {
      flags |= DISPLAY_HAS_RANDR;
      randr_current = randr_major > 1 || randr_minor >= 3;
      XRRSelectInput (dpy, root, RRScreenChangeNotifyMask | RRCrtcChangeNotifyMask | RROutputChangeNotifyMask);
      update_monitors ();
    }
}

// Update the cache before root events are delivered to terminal watchers.
void
rxvt_display::handle_monitor_event (XEvent &xev)
{
  if ((flags & DISPLAY_HAS_RANDR)
      && (xev.type == randr_event_base + RRScreenChangeNotify
          || xev.type == randr_event_base + RRNotify))
    {
      XRRUpdateConfiguration (&xev);
      update_monitors ();
    }
}

// Mode timings include the interlace and doublescan adjustments.
void
rxvt_display::update_monitors ()
{
  refresh_rate = 60.;
  double highest = 0.;
  XRRScreenResources *resources = randr_current
    ? XRRGetScreenResourcesCurrent (dpy, root)
    : XRRGetScreenResources (dpy, root);
  if (!resources)
    return;

  for (int i = 0; i < resources->ncrtc; i++)
    if (XRRCrtcInfo *crtc = XRRGetCrtcInfo (dpy, resources, resources->crtcs[i]))
      {
        if (crtc->mode && crtc->width && crtc->height)
          {
            for (int j = 0; j < resources->nmode; j++)
              if (resources->modes[j].id == crtc->mode)
                {
                  const XRRModeInfo &mode = resources->modes[j];
                  if (mode.hTotal && mode.vTotal)
                    {
                      double rate = double (mode.dotClock) / mode.hTotal / mode.vTotal;
                      if (mode.modeFlags & RR_DoubleScan) rate /= 2.;
                      if (mode.modeFlags & RR_Interlace)  rate *= 2.;
                      highest = max (highest, rate);
                    }
                  break;
                }
          }
        XRRFreeCrtcInfo (crtc);
      }
  XRRFreeScreenResources (resources);
  if (highest > 0.)
    refresh_rate = highest;
}
#endif

void
rxvt_term::update_refresh_rate ()
{
#if HAVE_XRANDR
  if (refresh_rate_auto && (display->flags & DISPLAY_HAS_RANDR))
    {
      ev_tstamp interval = 1. / display->refresh_rate;
      if (interval != refresh_interval)
        {
          refresh_interval = interval;
          // Reschedule pending drawing using the displays' new cadence.
          flush_ev.stop ();
          refresh_check ();
        }
    }
#endif
}
