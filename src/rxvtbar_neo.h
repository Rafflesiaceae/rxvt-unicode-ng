// Retained Lua bars. The manager is optional and exists only for terminals
// which actually register a bar; visibility never changes its reservations.
#ifndef RXVT_BAR_H
#define RXVT_BAR_H

#include <X11/Xlib.h>

struct rxvt_term;
struct lua_State;
struct rxvt_bar_state;

enum rxvt_bar_edge { BAR_TOP, BAR_RIGHT, BAR_BOTTOM, BAR_LEFT };

struct rxvt_bar_manager
{
  rxvt_term *term;
  rxvt_bar_state *s;
  bool geometry_dirty;

  explicit rxvt_bar_manager (rxvt_term *term);
  ~rxvt_bar_manager ();
  int inset (int edge) const;
  void dock ();
  void prepare ();
  void paint ();
  void invalidate (bool fonts = false);
  void cancel (const char *reason);
  bool pending () const;
  bool consume_pointer (XEvent &ev);
  void native_geometry (int &x, int &y, int &height) const;
  void x_cb (XEvent &ev);
};

int rxvt_bar_new (lua_State *L);
void rxvt_bar_register (lua_State *L);

#endif
