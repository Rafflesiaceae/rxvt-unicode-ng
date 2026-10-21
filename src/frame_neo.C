// Retained-frame allocation, background clearing and presentation.
#include "../config.h"
#include "rxvt.h"

// A pixmap has no window background, so reproduce solid and tiled backgrounds
// explicitly. Parent-relative transparency is offset into the parent's tile.
void
rxvt_term::scr_clear_rect (rxvt_drawable &d, int x, int y, int w, int h) noexcept
{
#ifdef HAVE_IMG
  if (bg_img)
    {
      XGCValues gcv;
      gcv.fill_style = FillTiled;
      gcv.tile = bg_img->pm;
      gcv.ts_x_origin = 0;
      gcv.ts_y_origin = 0;
# if ENABLE_TRANSPARENCY
      if (bg_flags & BG_IS_TRANSPARENT)
        {
          gcv.ts_x_origin = -window_vt_x;
          gcv.ts_y_origin = -window_vt_y;
        }
# endif
      XChangeGC (dpy, gc, GCFillStyle | GCTile | GCTileStipXOrigin | GCTileStipYOrigin, &gcv);
      XFillRectangle (dpy, d, gc, x, y, w, h);
      XSetFillStyle (dpy, gc, FillSolid);
      return;
    }
#endif

  XSetForeground (dpy, gc, pix_colors[Color_bg]);
  XFillRectangle (dpy, d, gc, x, y, w, h);
}

void
rxvt_term::scr_frame_resize () noexcept
{
  if (frame && frame_width == vt_width && frame_height == vt_height)
    return;

  // Replacing the drawable also discards its Xft picture and clipping state.
  delete drawable;
  if (frame)
    XFreePixmap (dpy, frame);
  frame_width = vt_width;
  frame_height = vt_height;
  frame = XCreatePixmap (dpy, vt, frame_width, frame_height, depth);
  drawable = new rxvt_drawable (this, frame);
  scr_clear_rect (*drawable, 0, 0, frame_width, frame_height);
  scr_touch (false);
}

void
rxvt_term::scr_present (int x, int y, int w, int h) noexcept
{
  // After a resize the old frame may be smaller than the exposed window.
  w = min (w, frame_width - x);
  h = min (h, frame_height - y);
  if (frame && mapped && w > 0 && h > 0)
    XCopyArea (dpy, frame, vt, gc, x, y, w, h, x, y);
}
