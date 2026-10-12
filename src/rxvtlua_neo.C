/*----------------------------------------------------------------------*
 * File:	rxvtlua_neo.C - embedded LuaJIT plugin system
 *----------------------------------------------------------------------*
 *
 * Loads every *.lua file from $XDG_CONFIG_HOME/urxvt/plugins (default
 * ~/.config/urxvt/plugins) when the first terminal is created. Each plugin
 * returns a table of hook functions (on_start, on_key_press, ...) which get
 * called with a terminal object and the hook arguments. See
 * doc/lua-plugins.md for the API.
 *
 * Startup cost and per-event overhead are kept minimal:
 *  - without any plugin file no lua state is ever created, the only cost
 *    is a single opendir() per terminal;
 *  - hooks that no plugin implements are skipped by a flag check at the
 *    call site (SHOULD_INVOKE/HOOK_INVOKE), before any argument conversion;
 *  - everything is plain lua C API, no lua code runs besides the plugins.
 *----------------------------------------------------------------------*/

#include "../config.h"
#include "rxvt.h"

#if ENABLE_LUA

#include "keyboard.h"
#include "version.h"

#include <dirent.h>
#include <fcntl.h>
#include <new>
#include <pwd.h>
#include <signal.h>
#include <sys/wait.h>

#include <lua.hpp>

rxvt_lua_interp rxvt_lua;

// hook names as seen by plugins, i.e. "on_" + the lowercased hook name
static const char *const hook_upper_names[] = {
# define def(sym) # sym,
# include "hookinc.h"
# undef def
};
static char hook_names[HOOK_NUM][32];

// registry references
static int hook_refs[HOOK_NUM]; // array of handler functions per hook, 0 if none
static int term_mt_ref;         // metatable of terminal objects
static int traceback_ref;       // debug.traceback

// the terminal the current hook/plugin code runs for, needed by functions
// that are not methods (urxvt.bind needs a terminal to parse keysyms)
static rxvt_term *cur_term;

// key bindings registered with urxvt.bind
struct lua_binding
{
  KeySym sym;
  unsigned int state;
  int fn_ref;
};
static vector<lua_binding> bindings;

// cells changed by t:highlight, restored after the refresh
struct saved_rend
{
  int row, col;
  rend_t rend;
};
static vector<saved_rend> highlights;
static rxvt_term *refresh_term; // terminal inside on_refresh_begin..end, if any

/////////////////////////////////////////////////////////////////////////////
// helpers

// Encodes the unicode character c as UTF-8 into buf (at least 4 bytes),
// returns the number of bytes.
static int
utf8_encode (unicode_t c, char *buf)
{
  if (c < 0x80)
    {
      buf[0] = c;
      return 1;
    }
  if (c < 0x800)
    {
      buf[0] = 0xc0 | (c >> 6);
      buf[1] = 0x80 | (c & 0x3f);
      return 2;
    }
  if (c < 0x10000)
    {
      buf[0] = 0xe0 | (c >> 12);
      buf[1] = 0x80 | ((c >> 6) & 0x3f);
      buf[2] = 0x80 | (c & 0x3f);
      return 3;
    }
  if (c < 0x110000)
    {
      buf[0] = 0xf0 | (c >> 18);
      buf[1] = 0x80 | ((c >> 12) & 0x3f);
      buf[2] = 0x80 | ((c >> 6) & 0x3f);
      buf[3] = 0x80 | (c & 0x3f);
      return 4;
    }
  // replacement character for anything invalid
  return utf8_encode (0xfffd, buf);
}

// Encodes one screen cell as UTF-8 into buf (at least CELL_UTF8_MAX bytes).
// Wide character continuation cells (NOCHAR) yield nothing, composed
// characters are expanded.
enum { CELL_COMPOSE_MAX = 16, CELL_UTF8_MAX = CELL_COMPOSE_MAX * 4 };

static int
cell_utf8 (text_t t, char *buf)
{
  if (t == NOCHAR)
    return 0;

#if ENABLE_COMBINING
  if (IS_COMPOSE (t))
    {
      wchar_t chars[CELL_COMPOSE_MAX];

      if (rxvt_composite.expand (t) > CELL_COMPOSE_MAX)
        return utf8_encode (0xfffd, buf);

      int n = rxvt_composite.expand (t, chars);
      int len = 0;

      for (int i = 0; i < n; i++)
        len += utf8_encode (chars[i], buf + len);

      return len;
    }
#endif

  return utf8_encode (t, buf);
}

// number of columns of a row that contain text
static int
row_len (rxvt_term *term, line_t &l)
{
  int len = l.l;
  clamp_it (len, 0, term->ncol);
  return len;
}

static void
push_wcs (lua_State *L, const wchar_t *str, int len)
{
  char *utf8 = rxvt_wcstoutf8 (str, len);
  lua_pushstring (L, utf8);
  free (utf8);
}

// Lua numbers are doubles, go through an integer type wide enough for all
// 32 bit values to get a well defined conversion.
static rend_t
check_rend (lua_State *L, int idx, rend_t def)
{
  return lua_isnoneornil (L, idx) ? def : (rend_t)(int64_t)luaL_checknumber (L, idx);
}

static void
push_xevent (lua_State *L, rxvt_term *term, XEvent *xe)
{
  lua_createtable (L, 0, 14);

#define setint(name, val) (lua_pushinteger (L, (val)), lua_setfield (L, -2, name))
#define setnum(name, val) (lua_pushnumber (L, (lua_Number)(val)), lua_setfield (L, -2, name))
#define setbool(name, val) (lua_pushboolean (L, (val)), lua_setfield (L, -2, name))

  setint ("type", xe->type);
  setnum ("window", xe->xany.window);
  setbool ("send_event", xe->xany.send_event);

  switch (xe->type)
    {
      case KeyPress:
      case KeyRelease:
      case ButtonPress:
      case ButtonRelease:
      case MotionNotify:
        {
          // the layout of these fields is shared by all five event types
          unsigned int state = xe->xmotion.state;

          setnum ("time", xe->xmotion.time);
          setint ("x", xe->xmotion.x);
          setint ("y", xe->xmotion.y);
          setint ("x_root", xe->xmotion.x_root);
          setint ("y_root", xe->xmotion.y_root);
          // absolute row (negative rows are in the scrollback), like t:line
          setint ("row", xe->xmotion.y / term->fheight + term->view_start);
          setint ("col", xe->xmotion.x / term->fwidth);
          setnum ("state", state);
          setbool ("shift", state & ShiftMask);
          setbool ("ctrl", state & ControlMask);
          setbool ("meta", state & term->ModMetaMask);

          if (xe->type == KeyPress || xe->type == KeyRelease)
            setint ("keycode", xe->xkey.keycode);
          else if (xe->type == ButtonPress || xe->type == ButtonRelease)
            setint ("button", xe->xbutton.button);
        }
        break;

      case ConfigureNotify:
        setint ("x", xe->xconfigure.x);
        setint ("y", xe->xconfigure.y);
        setint ("width", xe->xconfigure.width);
        setint ("height", xe->xconfigure.height);
        break;

      case PropertyNotify:
        setnum ("atom", xe->xproperty.atom);
        setint ("state", xe->xproperty.state);
        setnum ("time", xe->xproperty.time);
        break;

      case ClientMessage:
        setnum ("message_type", xe->xclient.message_type);
        setint ("format", xe->xclient.format);
        lua_createtable (L, 5, 0);
        for (int i = 0; i < 5; i++)
          {
            lua_pushnumber (L, (lua_Number)xe->xclient.data.l[i]);
            lua_rawseti (L, -2, i + 1);
          }
        lua_setfield (L, -2, "data");
        break;
    }

#undef setint
#undef setnum
#undef setbool
}

// Pushes the hook arguments, returns their number.
static int
push_args (lua_State *L, rxvt_term *term, va_list ap)
{
  int n = 0;

  for (;; n++)
    switch ((data_type)va_arg (ap, int))
      {
        case DT_END:
          return n;

        case DT_INT:
          lua_pushinteger (L, va_arg (ap, int));
          break;

        case DT_LONG:
          lua_pushnumber (L, (lua_Number)va_arg (ap, long));
          break;

        case DT_STR:
          lua_pushstring (L, va_arg (ap, char *));
          break;

        case DT_STR_LEN:
          {
            char *str = va_arg (ap, char *);
            int len = va_arg (ap, int);
            lua_pushlstring (L, str, len);
          }
          break;

        case DT_WCS_LEN:
          {
            wchar_t *str = va_arg (ap, wchar_t *);
            int len = va_arg (ap, int);
            push_wcs (L, str, len);
          }
          break;

        case DT_LCS_LEN:
          {
            long *str = va_arg (ap, long *);
            int len = va_arg (ap, int);

            lua_createtable (L, len, 0);
            for (int i = 0; i < len; i++)
              {
                lua_pushnumber (L, (lua_Number)str[i]);
                lua_rawseti (L, -2, i + 1);
              }
          }
          break;

        case DT_XEVENT:
          push_xevent (L, term, va_arg (ap, XEvent *));
          break;

        default:
          rxvt_fatal ("FATAL: unable to pass unknown hook argument type to lua\n");
      }
}

// Calls the function at the top of the stack (below its nargs arguments)
// in protected mode, reporting errors with a traceback. Returns whether the
// call succeeded, leaving nresults values (or nothing on error).
static bool
pcall (lua_State *L, int nargs, int nresults, const char *what)
{
  int func = lua_gettop (L) - nargs;

  lua_rawgeti (L, LUA_REGISTRYINDEX, traceback_ref);
  lua_insert (L, func);

  int status = lua_pcall (L, nargs, nresults, func);
  lua_remove (L, func);

  if (status)
    {
      rxvt_warn ("lua: %s: %s\n", what, lua_tostring (L, -1));
      lua_pop (L, 1);
      return false;
    }

  return true;
}

// Returns the terminal of the terminal object at index 1, raising an error
// for destroyed terminals.
static rxvt_term *
check_term (lua_State *L)
{
  luaL_checktype (L, 1, LUA_TTABLE);
  lua_rawgeti (L, 1, 0);
  rxvt_term *term = (rxvt_term *)lua_touserdata (L, -1);
  lua_pop (L, 1);

  if (!term)
    luaL_error (L, "terminal has been destroyed");

  return term;
}

// Checks that row is a valid row number of term and returns its line.
static line_t &
check_row (lua_State *L, rxvt_term *term, int idx)
{
  int row = luaL_checkinteger (L, idx);

  if (!IN_RANGE_EXC (row, term->top_row, term->nrow))
    luaL_error (L, "row %d out of range [%d, %d)", row, term->top_row, term->nrow);

  return ROW_of (term, row);
}

// Applies (r & and_mask) | or_mask to the columns [c0, c1) of line l.
// Font bits are never touched by the masks, but the font is reselected if
// the style (bold/italic) changes.
static void
apply_rend (rxvt_term *term, line_t &l, int c0, int c1, rend_t and_mask, rend_t or_mask)
{
  and_mask |= RS_fontMask;
  or_mask &= ~RS_fontMask;

  for (int col = c0; col < c1; col++)
    {
      rend_t r = (l.r[col] & and_mask) | or_mask;

      if (GET_STYLE (r) != GET_STYLE (l.r[col]))
        r = SET_FONT (r, FONTSET_of (term, r)->find_font (l.t[col]));

      l.r[col] = r;
    }
}

/////////////////////////////////////////////////////////////////////////////
// terminal methods

// t:nrow () -> rows of the screen
static int
t_nrow (lua_State *L)
{
  lua_pushinteger (L, check_term (L)->nrow);
  return 1;
}

// t:ncol () -> columns of the screen
static int
t_ncol (lua_State *L)
{
  lua_pushinteger (L, check_term (L)->ncol);
  return 1;
}

// t:top_row () -> row number of the oldest scrollback line (<= 0)
static int
t_top_row (lua_State *L)
{
  lua_pushinteger (L, check_term (L)->top_row);
  return 1;
}

// t:view_start ([row]) -> row shown at the top of the window (<= 0),
// scrolls the view first if row is given
static int
t_view_start (lua_State *L)
{
  rxvt_term *term = check_term (L);

  if (!lua_isnoneornil (L, 2))
    term->scr_changeview (luaL_checkinteger (L, 2));

  lua_pushinteger (L, term->view_start);
  return 1;
}

// t:cursor () -> row, col
static int
t_cursor (lua_State *L)
{
  rxvt_term *term = check_term (L);
  lua_pushinteger (L, term->screen.cur.row);
  lua_pushinteger (L, term->screen.cur.col);
  return 2;
}

// t:focus () -> whether the window has the input focus
static int
t_focus (lua_State *L)
{
  lua_pushboolean (L, check_term (L)->focus);
  return 1;
}

// t:font_size () -> width, height of a character cell in pixels
static int
t_font_size (lua_State *L)
{
  rxvt_term *term = check_term (L);
  lua_pushinteger (L, term->fwidth);
  lua_pushinteger (L, term->fheight);
  return 2;
}

// t:window () -> X window id of the toplevel window
static int
t_window (lua_State *L)
{
  lua_pushnumber (L, (lua_Number)check_term (L)->parent);
  return 1;
}

// t:line (row) -> text, wrapped
// The UTF-8 text of a row, wrapped tells whether the line continues on the
// next row. Each column contributes its character, the second column of
// wide characters contributes nothing.
static int
t_line (lua_State *L)
{
  rxvt_term *term = check_term (L);
  line_t &l = check_row (L, term, 2);
  int len = row_len (term, l);

  luaL_Buffer b;
  luaL_buffinit (L, &b);

  for (int col = 0; col < len; col++)
    {
      char buf[CELL_UTF8_MAX];
      luaL_addlstring (&b, buf, cell_utf8 (l.t[col], buf));
    }

  luaL_pushresult (&b);
  lua_pushboolean (L, l.is_longer ());
  return 2;
}

// t:col (row, byte) -> column of the character starting at the (1-based)
// byte offset byte of t:line (row), or the column after the text for
// offsets beyond it
static int
t_col (lua_State *L)
{
  rxvt_term *term = check_term (L);
  line_t &l = check_row (L, term, 2);
  int want = luaL_checkinteger (L, 3) - 1;
  int len = row_len (term, l);
  int ofs = 0;
  int col;

  for (col = 0; col < len; col++)
    {
      char buf[CELL_UTF8_MAX];
      int n = cell_utf8 (l.t[col], buf);

      // NOCHAR cells (n == 0) belong to the character before them
      if (n && ofs >= want)
        break;

      ofs += n;
    }

  lua_pushinteger (L, col);
  return 1;
}

// t:rend (row, c0, c1, and_mask, or_mask)
// Permanently changes the rendition of the columns [c0, c1) of a row until
// the line changes again, use it in on_line_update.
static int
t_rend (lua_State *L)
{
  rxvt_term *term = check_term (L);
  line_t &l = check_row (L, term, 2);
  int c0 = luaL_checkinteger (L, 3);
  int c1 = luaL_checkinteger (L, 4);
  rend_t and_mask = check_rend (L, 5, ~(rend_t)0);
  rend_t or_mask  = check_rend (L, 6, 0);

  clamp_it (c0, 0, term->ncol);
  clamp_it (c1, c0, term->ncol);

  apply_rend (term, l, c0, c1, and_mask, or_mask);
  term->want_refresh = 1;
  return 0;
}

// t:highlight (row, c0, c1, and_mask, or_mask)
// Like t:rend, but only for the refresh in progress, so it is only
// allowed in on_refresh_begin.
static int
t_highlight (lua_State *L)
{
  rxvt_term *term = check_term (L);
  int row = luaL_checkinteger (L, 2);
  int c0 = luaL_checkinteger (L, 3);
  int c1 = luaL_checkinteger (L, 4);
  rend_t and_mask = check_rend (L, 5, ~(rend_t)0);
  rend_t or_mask  = check_rend (L, 6, 0);

  if (refresh_term != term)
    return luaL_error (L, "t:highlight is only allowed in on_refresh_begin");

  // silently ignore rows outside of the view, it saves plugins the check
  if (!IN_RANGE_EXC (row - term->view_start, 0, term->nrow)
      || !IN_RANGE_EXC (row, term->top_row, term->nrow))
    return 0;

  clamp_it (c0, 0, term->ncol);
  clamp_it (c1, c0, term->ncol);

  line_t &l = ROW_of (term, row);

  for (int col = c0; col < c1; col++)
    {
      saved_rend saved = { row, col, l.r[col] };
      highlights.push_back (saved);
    }

  apply_rend (term, l, c0, c1, and_mask, or_mask);
  return 0;
}

// t:write (data) - sends data to the program, as if it was typed
static int
t_write (lua_State *L)
{
  rxvt_term *term = check_term (L);
  size_t len;
  const char *data = luaL_checklstring (L, 2, &len);
  term->tt_write (data, len);
  return 0;
}

#if defined (KEYSYM_RESOURCE)
// t:feed (data) - processes data as if the program had output it
static int
t_feed (lua_State *L)
{
  rxvt_term *term = check_term (L);
  size_t len;
  const char *data = luaL_checklstring (L, 2, &len);
  term->cmdbuf_append (data, len);
  return 0;
}
#endif

// t:refresh () - schedules a redraw, needed after changes made outside of
// hooks (e.g. in timers)
static int
t_refresh (lua_State *L)
{
  rxvt_term *term = check_term (L);
  term->want_refresh = 1;
  term->refresh_check ();
  return 0;
}

// t:overlay (x, y, w, h) - opens the overlay window (there is only one),
// negative x/y count from the right/bottom, the border adds a cell on each
// side
static int
t_overlay (lua_State *L)
{
  rxvt_term *term = check_term (L);
  term->scr_overlay_new (luaL_checkinteger (L, 2), luaL_checkinteger (L, 3),
                         luaL_checkinteger (L, 4), luaL_checkinteger (L, 5));
  return 0;
}

// t:overlay_text (x, y, text [, and_mask, or_mask]) - writes text into the
// overlay, the masks apply to the default overlay rendition
static int
t_overlay_text (lua_State *L)
{
  rxvt_term *term = check_term (L);
  int x = luaL_checkinteger (L, 2);
  int y = luaL_checkinteger (L, 3);
  const char *text = luaL_checkstring (L, 4);
  rend_t and_mask = check_rend (L, 5, ~(rend_t)0);
  rend_t or_mask  = check_rend (L, 6, 0);
  rend_t rend = (OVERLAY_RSTYLE & (and_mask | RS_fontMask)) | (or_mask & ~RS_fontMask);

  wchar_t *wtext = rxvt_utf8towcs (text);

  for (wchar_t *s = wtext; *s; s++)
    {
      text_t t = *s;
      int width = WCWIDTH (t);

      while (width-- > 0)
        {
          term->scr_overlay_set (x++, y, t, rend);
          t = NOCHAR;
        }
    }

  free (wtext);
  term->want_refresh = 1;
  return 0;
}

// t:overlay_off () - closes the overlay
static int
t_overlay_off (lua_State *L)
{
  check_term (L)->scr_overlay_off ();
  return 0;
}

// t:selection ([clipboard]) -> the selected (or clipboard) text, or nil
static int
t_selection (lua_State *L)
{
  rxvt_term *term = check_term (L);
  bool clipboard = lua_toboolean (L, 2);
  wchar_t *text    = clipboard ? term->selection.clip_text : term->selection.text;
  unsigned int len = clipboard ? term->selection.clip_len  : term->selection.len;

  if (text)
    push_wcs (L, text, len);
  else
    lua_pushnil (L);

  return 1;
}

// t:set_selection (text [, clipboard]) -> whether the selection could be
// claimed, makes text the PRIMARY (or CLIPBOARD) selection
static int
t_set_selection (lua_State *L)
{
  rxvt_term *term = check_term (L);
  const char *text = luaL_checkstring (L, 2);
  bool clipboard = lua_toboolean (L, 3);
  wchar_t *&sel    = clipboard ? term->selection.clip_text : term->selection.text;
  unsigned int &len = clipboard ? term->selection.clip_len  : term->selection.len;

  free (sel);
  sel = rxvt_utf8towcs (text);
  len = wcslen (sel);

  lua_pushboolean (L, term->selection_grab (CurrentTime, clipboard));
  return 1;
}

// t:resource (name) -> value of the X resource URxvt.<name>, or nil
static int
t_resource (lua_State *L)
{
  rxvt_term *term = check_term (L);
  lua_pushstring (L, term->x_resource (luaL_checkstring (L, 2)));
  return 1;
}

static const luaL_Reg term_methods[] = {
  { "nrow",          t_nrow          },
  { "ncol",          t_ncol          },
  { "top_row",       t_top_row       },
  { "view_start",    t_view_start    },
  { "cursor",        t_cursor        },
  { "focus",         t_focus         },
  { "font_size",     t_font_size     },
  { "window",        t_window        },
  { "line",          t_line          },
  { "col",           t_col           },
  { "rend",          t_rend          },
  { "highlight",     t_highlight     },
  { "write",         t_write         },
#if defined (KEYSYM_RESOURCE)
  { "feed",          t_feed          },
#endif
  { "refresh",       t_refresh       },
  { "overlay",       t_overlay       },
  { "overlay_text",  t_overlay_text  },
  { "overlay_off",   t_overlay_off   },
  { "selection",     t_selection     },
  { "set_selection", t_set_selection },
  { "resource",      t_resource      },
  { 0, 0 }
};

/////////////////////////////////////////////////////////////////////////////
// urxvt module

// urxvt.bind (keyspec, fn) - calls fn (t) when keyspec (keysym resource
// syntax, e.g. "M-s" or "C-S-Up") is pressed. The key is consumed unless fn
// returns false. Like keysym resources, extra modifiers are ignored.
static int
u_bind (lua_State *L)
{
  const char *spec = luaL_checkstring (L, 1);
  luaL_checktype (L, 2, LUA_TFUNCTION);

  if (!cur_term)
    return luaL_error (L, "urxvt.bind needs to be called from plugin or hook code");

  lua_binding b;
  int sym = cur_term->parse_keysym (spec, b.state);

  if (sym == -1)
    return luaL_error (L, "unable to parse key '%s'", spec);

  b.sym = sym;
  lua_pushvalue (L, 2);
  b.fn_ref = luaL_ref (L, LUA_REGISTRYINDEX);
  bindings.push_back (b);

  rxvt_lua.should_invoke[HOOK_KEY_PRESS] = 1;
  return 0;
}

// urxvt.style {fg=, bg=, bold=, italic=, underline=, reverse=, blink=}
//   -> and_mask, or_mask
// fg/bg are color indices (0-15 for the basic colors) or "default", the
// attributes are set (true) or cleared (false), omitted ones stay as they are.
static int
u_style (lua_State *L)
{
  luaL_checktype (L, 1, LUA_TTABLE);

  rend_t and_mask = ~(rend_t)0;
  rend_t or_mask = 0;

  static const struct { const char *name; rend_t bit; } attrs[] = {
    { "bold",      RS_Bold   },
    { "italic",    RS_Italic },
    { "underline", RS_Uline  },
    { "reverse",   RS_RVid   },
    { "blink",     RS_Blink  },
  };

  for (unsigned int i = 0; i < ecb_array_length (attrs); i++)
    {
      lua_getfield (L, 1, attrs[i].name);
      if (!lua_isnil (L, -1))
        {
          and_mask &= ~attrs[i].bit;
          if (lua_toboolean (L, -1))
            or_mask |= attrs[i].bit;
        }
      lua_pop (L, 1);
    }

  static const struct { const char *name; rend_t mask; int shift; int def; } colors[] = {
    { "fg", RS_fgMask, RS_fgShift, Color_fg },
    { "bg", RS_bgMask, RS_bgShift, Color_bg },
  };

  for (unsigned int i = 0; i < ecb_array_length (colors); i++)
    {
      lua_getfield (L, 1, colors[i].name);
      if (!lua_isnil (L, -1))
        {
          int color;

          if (lua_type (L, -1) == LUA_TSTRING && !strcmp (lua_tostring (L, -1), "default"))
            color = colors[i].def;
          else
            {
              int index = luaL_checkinteger (L, -1);

              if (!IN_RANGE_INC (index, 0, maxTermCOLOR - minCOLOR))
                return luaL_error (L, "%s color %d out of range [0, %d]", colors[i].name, index, maxTermCOLOR - minCOLOR);

              color = minCOLOR + index;
            }

          and_mask &= ~colors[i].mask;
          or_mask |= (rend_t)color << colors[i].shift;
        }
      lua_pop (L, 1);
    }

  lua_pushnumber (L, and_mask);
  lua_pushnumber (L, or_mask);
  return 2;
}

// urxvt.spawn (argv) - starts a detached program, argv is a table of
// arguments or a string for /bin/sh -c. Returns whether fork succeeded.
static int
u_spawn (lua_State *L)
{
  // build the argument vector before forking, the child must not touch lua
  const char *sh_argv[] = { "/bin/sh", "-c", 0, 0 };
  const char **argv = sh_argv;

  if (lua_type (L, 1) == LUA_TSTRING)
    sh_argv[2] = lua_tostring (L, 1);
  else
    {
      luaL_checktype (L, 1, LUA_TTABLE);
      int n = lua_objlen (L, 1);

      if (n < 1)
        return luaL_error (L, "urxvt.spawn needs a program to run");

      // lives on the lua stack, so it is freed even if an argument is bad
      argv = (const char **)lua_newuserdata (L, (n + 1) * sizeof (char *));

      for (int i = 0; i < n; i++)
        {
          lua_rawgeti (L, 1, i + 1);
          argv[i] = luaL_checkstring (L, -1);
          lua_pop (L, 1); // the table keeps the string alive
        }

      argv[n] = 0;
    }

  pid_t pid = fork ();

  if (pid == 0)
    {
      // double fork, so the program is reparented to init and never
      // becomes a zombie of the terminal
      if (fork () == 0)
        {
          setsid ();

          // don't leak the pty or the X connection into the program
          for (int fd = sysconf (_SC_OPEN_MAX) - 1; fd > 2; fd--)
            close (fd);

          signal (SIGCHLD, SIG_DFL);
          signal (SIGPIPE, SIG_DFL);

          execvp (argv[0], (char **)argv);
          _exit (127);
        }

      _exit (0);
    }

  if (pid > 0)
    // libev's child watcher may reap it before us, that is fine
    while (waitpid (pid, 0, 0) < 0 && errno == EINTR)
      ;

  lua_pushboolean (L, pid > 0);
  return 1;
}

// timers created by urxvt.timer
struct lua_timer
{
  ev::timer w;
  lua_State *L;
  int fn_ref;
  int self_ref; // keeps the timer alive while it is active, 0 if not

  void cb (ev::timer &w, int revents);

  // Plugin timers must not keep urxvt running after the last terminal is
  // gone, so they are taken out of the reference count of the event loop
  // while active (see "ev_ref/ev_unref" in the libev documentation).
  void start ()
  {
    w.start ();
    ev_unref (EV_DEFAULT_UC);
  }

  void stop ()
  {
    if (w.is_active ())
      {
        ev_ref (EV_DEFAULT_UC);
        w.stop ();
      }
  }

  void unanchor ()
  {
    if (self_ref)
      {
        luaL_unref (L, LUA_REGISTRYINDEX, self_ref);
        self_ref = 0;
      }
  }
};

void
lua_timer::cb (ev::timer &w, int revents)
{
  // libev already stopped an expired one-shot timer, which dropped the
  // reference that start () had given back
  if (!w.is_active ())
    ev_ref (EV_DEFAULT_UC);

  lua_rawgeti (L, LUA_REGISTRYINDEX, fn_ref);
  pcall (L, 0, 0, "timer");

  // one-shot timers become collectable once they have fired, unless the
  // function restarted them
  if (!w.is_active ())
    unanchor ();
}

static lua_timer *
check_timer (lua_State *L)
{
  return (lua_timer *)luaL_checkudata (L, 1, "urxvt.timer");
}

// timer:start ([after [, repeat]]) - (re)starts the timer
static int
timer_start (lua_State *L)
{
  lua_timer *timer = check_timer (L);

  // restarting an active timer starts it over with the full delay
  timer->stop ();

  if (!lua_isnoneornil (L, 2))
    timer->w.set (luaL_checknumber (L, 2), luaL_optnumber (L, 3, 0.));

  timer->start ();

  if (!timer->self_ref)
    {
      lua_pushvalue (L, 1);
      timer->self_ref = luaL_ref (L, LUA_REGISTRYINDEX);
    }

  return 0;
}

// timer:stop ()
static int
timer_stop (lua_State *L)
{
  lua_timer *timer = check_timer (L);
  timer->stop ();
  timer->unanchor ();
  return 0;
}

static int
timer_gc (lua_State *L)
{
  lua_timer *timer = check_timer (L);
  timer->stop ();
  luaL_unref (L, LUA_REGISTRYINDEX, timer->fn_ref);
  timer->~lua_timer ();
  return 0;
}

// urxvt.timer (after, fn [, repeat]) -> timer
// Calls fn after `after` seconds and then every `repeat` seconds, if given.
// Active timers stay alive without references, stop them with timer:stop.
// They don't keep urxvt running once all terminals are closed.
static int
u_timer (lua_State *L)
{
  double after = luaL_checknumber (L, 1);
  luaL_checktype (L, 2, LUA_TFUNCTION);
  double repeat = luaL_optnumber (L, 3, 0.);

  lua_timer *timer = new (lua_newuserdata (L, sizeof (lua_timer))) lua_timer;
  luaL_getmetatable (L, "urxvt.timer");
  lua_setmetatable (L, -2);

  timer->L = L;
  lua_pushvalue (L, 2);
  timer->fn_ref = luaL_ref (L, LUA_REGISTRYINDEX);
  timer->self_ref = 0;
  timer->w.set<lua_timer, &lua_timer::cb> (timer);
  timer->w.set (after, repeat);

  lua_pushcfunction (L, timer_start);
  lua_pushvalue (L, -2);
  lua_call (L, 1, 0);

  return 1;
}

// urxvt.warn (msg) - prints a message on stderr
static int
u_warn (lua_State *L)
{
  rxvt_warn ("%s\n", luaL_checkstring (L, 1));
  return 0;
}

// urxvt.keysym_name (keysym) -> name of a keysym, e.g. "Return", or nil
static int
u_keysym_name (lua_State *L)
{
  lua_pushstring (L, XKeysymToString (luaL_checkinteger (L, 1)));
  return 1;
}

static const luaL_Reg urxvt_functions[] = {
  { "bind",        u_bind        },
  { "style",       u_style       },
  { "spawn",       u_spawn       },
  { "timer",       u_timer       },
  { "warn",        u_warn        },
  { "keysym_name", u_keysym_name },
  { 0, 0 }
};

/////////////////////////////////////////////////////////////////////////////
// plugin loading

// $XDG_CONFIG_HOME/urxvt/plugins, or ~/.config/urxvt/plugins
static bool
plugin_dir (char *buf, size_t size)
{
  const char *config = getenv ("XDG_CONFIG_HOME");

  if (config && *config == '/')
    return snprintf (buf, size, "%s/urxvt/plugins", config) < (int)size;

  const char *home = getenv ("HOME");

  if (!home || !*home)
    {
      struct passwd *pw = getpwuid (getuid ());
      home = pw ? pw->pw_dir : 0;
    }

  return home && snprintf (buf, size, "%s/.config/urxvt/plugins", home) < (int)size;
}

static int
compare_names (const void *a, const void *b)
{
  return strcmp (*(char *const *)a, *(char *const *)b);
}

// Collects the plugin file names of dir, sorted. Returns 0 if there are
// none, otherwise a 0-terminated array to free with free_names.
static char **
find_plugins (const char *dir)
{
  DIR *d = opendir (dir);

  if (!d)
    return 0;

  vector<char *> names;

  while (struct dirent *e = readdir (d))
    {
      size_t len = strlen (e->d_name);

      // skip hidden files, e.g. editor backups
      if (e->d_name[0] != '.' && len > 4 && !strcmp (e->d_name + len - 4, ".lua"))
        names.push_back (strdup (e->d_name));
    }

  closedir (d);

  if (names.empty ())
    return 0;

  char **result = (char **)malloc ((names.size () + 1) * sizeof (char *));
  memcpy (result, &names[0], names.size () * sizeof (char *));
  result[names.size ()] = 0;
  qsort (result, names.size (), sizeof (char *), compare_names);

  return result;
}

// Registers the hook functions of the plugin table at the top of the stack.
static void
register_hooks (lua_State *L, const char *name)
{
  for (int htype = 0; htype < HOOK_NUM; htype++)
    {
      lua_getfield (L, -1, hook_names[htype]);

      if (lua_isfunction (L, -1))
        {
          if (!hook_refs[htype])
            {
              lua_newtable (L);
              hook_refs[htype] = luaL_ref (L, LUA_REGISTRYINDEX);
            }

          lua_rawgeti (L, LUA_REGISTRYINDEX, hook_refs[htype]);
          lua_insert (L, -2);
          lua_rawseti (L, -2, lua_objlen (L, -2) + 1);
          rxvt_lua.should_invoke[htype] = 1;
        }

      lua_pop (L, 1);
    }

  // all other fields starting with on_ are most likely typos
  lua_pushnil (L);
  while (lua_next (L, -2))
    {
      if (lua_type (L, -2) == LUA_TSTRING)
        {
          const char *key = lua_tostring (L, -2);
          bool known = strncmp (key, "on_", 3);

          for (int htype = 0; !known && htype < HOOK_NUM; htype++)
            known = !strcmp (key, hook_names[htype]);

          if (!known)
            rxvt_warn ("lua: %s: unknown hook '%s', ignoring.\n", name, key);
        }

      lua_pop (L, 1);
    }
}

static void
create_state (rxvt_term *term, const char *dir, char **plugins)
{
  lua_State *L = luaL_newstate ();

  if (!L)
    {
      rxvt_warn ("lua: unable to create the lua state, plugins disabled.\n");
      return;
    }

  luaL_openlibs (L);

  for (int htype = 0; htype < HOOK_NUM; htype++)
    {
      snprintf (hook_names[htype], sizeof (hook_names[htype]), "on_%s", hook_upper_names[htype]);
      for (char *p = hook_names[htype]; *p; p++)
        *p = tolower (*p);
    }

  lua_getglobal (L, "debug");
  lua_getfield (L, -1, "traceback");
  traceback_ref = luaL_ref (L, LUA_REGISTRYINDEX);
  lua_pop (L, 1);

  // the terminal object metatable, methods are looked up in it
  lua_createtable (L, 0, 2);
  lua_newtable (L);
  luaL_register (L, 0, term_methods);
  lua_setfield (L, -2, "__index");
  lua_pushliteral (L, "urxvt.terminal");
  lua_setfield (L, -2, "__name");
  term_mt_ref = luaL_ref (L, LUA_REGISTRYINDEX);

  luaL_newmetatable (L, "urxvt.timer");
  lua_newtable (L);
  lua_pushcfunction (L, timer_start);
  lua_setfield (L, -2, "start");
  lua_pushcfunction (L, timer_stop);
  lua_setfield (L, -2, "stop");
  lua_setfield (L, -2, "__index");
  lua_pushcfunction (L, timer_gc);
  lua_setfield (L, -2, "__gc");
  lua_pop (L, 1);

  // the global urxvt module, also available via require "urxvt"
  luaL_register (L, "urxvt", urxvt_functions);
  lua_pushstring (L, VERSION);
  lua_setfield (L, -2, "version");
  lua_pushstring (L, dir);
  lua_setfield (L, -2, "plugin_dir");
  lua_pop (L, 1);

  // plugins can keep helper modules in plugins/lib, which is not autoloaded
  lua_getglobal (L, "package");
  lua_pushfstring (L, "%s/lib/?.lua;", dir);
  lua_getfield (L, -2, "path");
  lua_concat (L, 2);
  lua_setfield (L, -2, "path");
  lua_pop (L, 1);

  rxvt_lua.L = L;

  // the terminal is not usable before its lua object exists, which needs
  // the state, but keysym parsing in urxvt.bind already works
  cur_term = term;

  for (char **name = plugins; *name; name++)
    {
      char path[PATH_MAX];
      snprintf (path, sizeof (path), "%s/%s", dir, *name);

      if (luaL_loadfile (L, path))
        {
          rxvt_warn ("lua: %s\n", lua_tostring (L, -1));
          lua_pop (L, 1);
          continue;
        }

      if (!pcall (L, 0, 1, *name))
        continue;

      if (lua_istable (L, -1))
        register_hooks (L, *name);
      else if (!lua_isnil (L, -1))
        rxvt_warn ("lua: %s: plugins have to return a table of hooks (or nothing).\n", *name);

      lua_pop (L, 1);
    }

  cur_term = 0;

  // the interpreter needs these to manage the terminal objects and the
  // temporary highlights, regardless of the plugins
  rxvt_lua.should_invoke[HOOK_INIT] = 1;
  rxvt_lua.should_invoke[HOOK_DESTROY] = 1;

  if (rxvt_lua.should_invoke[HOOK_REFRESH_BEGIN])
    rxvt_lua.should_invoke[HOOK_REFRESH_END] = 1;

  // motion events without pressed buttons need to be enabled on start
  if (rxvt_lua.should_invoke[HOOK_MOTION_NOTIFY])
    rxvt_lua.should_invoke[HOOK_START] = 1;
}

bool
rxvt_lua_interp::init (rxvt_term *term)
{
  // the plugins are loaded once, by the first terminal (that finds any)
  if (!L)
    {
      char dir[PATH_MAX];

      if (!plugin_dir (dir, sizeof (dir)))
        return false;

      char **plugins = find_plugins (dir);

      if (!plugins)
        return false;

      create_state (term, dir, plugins);

      for (char **name = plugins; *name; name++)
        free (*name);
      free (plugins);

      if (!L)
        return false;
    }

  // the terminal object, a table so plugins can store per-terminal state
  // in it, with the terminal pointer at index 0
  lua_createtable (L, 0, 1);
  lua_pushlightuserdata (L, term);
  lua_rawseti (L, -2, 0);
  lua_rawgeti (L, LUA_REGISTRYINDEX, term_mt_ref);
  lua_setmetatable (L, -2);
  term->lua.ref = luaL_ref (L, LUA_REGISTRYINDEX);

  return true;
}

/////////////////////////////////////////////////////////////////////////////
// hook invocation

// Calls the urxvt.bind function matching a key press, if any. Returns
// whether the key was consumed.
static bool
invoke_binding (lua_State *L, rxvt_term *term, XEvent *xe, KeySym sym)
{
  // map the state like keyboard_manager::lookup_keysym
  unsigned int state = xe->xkey.state & OtherModMask;

  if (state & term->ModMetaMask)    state |= MetaMask;
  if (state & term->ModNumLockMask) state |= NumLockMask;
  if (state & term->ModLevel3Mask)  state |= Level3Mask;

  if (!!(term->priv_modes & PrivMode_aplKP) != !!(state & ShiftMask))
    state |= AppKeypadMask;

  for (unsigned int i = 0; i < bindings.size (); i++)
    if (bindings[i].sym == sym && (bindings[i].state & state) == bindings[i].state)
      {
        lua_rawgeti (L, LUA_REGISTRYINDEX, bindings[i].fn_ref);
        lua_rawgeti (L, LUA_REGISTRYINDEX, term->lua.ref);

        if (!pcall (L, 1, 1, "key binding"))
          return true;

        bool consumed = !(lua_isboolean (L, -1) && !lua_toboolean (L, -1));
        lua_pop (L, 1);
        return consumed;
      }

  return false;
}

bool
rxvt_lua_interp::invoke (rxvt_term *term, int htype, ...)
{
  if (!should_invoke[htype] || !term->lua.ref)
    return false;

  int base = lua_gettop (L);
  rxvt_term *prev_term = cur_term;
  cur_term = term;

  bool consumed = false;

  // pre-handling
  if (htype == HOOK_REFRESH_BEGIN)
    refresh_term = term;
  else if (htype == HOOK_START && should_invoke[HOOK_MOTION_NOTIFY])
    {
      term->vt_emask_perl |= PointerMotionMask;
      term->vt_select_input ();
    }
  else if (htype == HOOK_KEY_PRESS && bindings.size ())
    {
      va_list ap;
      va_start (ap, htype);
      va_arg (ap, int);
      XEvent *xe = va_arg (ap, XEvent *);
      va_arg (ap, int);
      KeySym sym = va_arg (ap, int);
      va_end (ap);

      consumed = invoke_binding (L, term, xe, sym);
    }

  // call the hook functions of all plugins until one consumes the event
  if (!consumed && hook_refs[htype])
    {
      lua_rawgeti (L, LUA_REGISTRYINDEX, hook_refs[htype]);
      int handlers = lua_gettop (L);

      lua_rawgeti (L, LUA_REGISTRYINDEX, term->lua.ref);

      va_list ap;
      va_start (ap, htype);
      int nargs = push_args (L, term, ap) + 1;
      va_end (ap);

      int args = handlers + 1;
      int n = lua_objlen (L, handlers);

      for (int i = 1; i <= n && !consumed; i++)
        {
          lua_rawgeti (L, handlers, i);

          // handlers that failed before have been disabled
          if (!lua_isfunction (L, -1))
            {
              lua_pop (L, 1);
              continue;
            }

          for (int arg = 0; arg < nargs; arg++)
            lua_pushvalue (L, args + arg);

          if (pcall (L, nargs, 1, hook_names[htype]))
            {
              consumed = lua_toboolean (L, -1);
              lua_pop (L, 1);
            }
          else
            {
              // an error is most likely going to repeat on every call,
              // e.g. for every refresh, so report it only once
              rxvt_warn ("lua: disabling this %s handler.\n", hook_names[htype]);
              lua_pushboolean (L, 0);
              lua_rawseti (L, handlers, i);
            }
        }
    }

  lua_settop (L, base);

  // post-handling
  if (htype == HOOK_REFRESH_END)
    {
      // restore in reverse order, so overlapping highlights end up with
      // the original rendition
      for (int i = highlights.size (); i--; )
        ROW_of (term, highlights[i].row).r[highlights[i].col] = highlights[i].rend;

      highlights.clear ();
      refresh_term = 0;
    }
  else if (htype == HOOK_DESTROY)
    {
      // invalidate the object, plugins might still hold references to it
      lua_rawgeti (L, LUA_REGISTRYINDEX, term->lua.ref);
      lua_pushnil (L);
      lua_rawseti (L, -2, 0);
      lua_pop (L, 1);
      luaL_unref (L, LUA_REGISTRYINDEX, term->lua.ref);
      term->lua.ref = 0;
    }

  cur_term = prev_term;
  return consumed;
}

#endif
