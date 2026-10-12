/*
 * rxvtlua_neo.h - embedded LuaJIT plugin system
 *
 * Plugins are the *.lua files in $XDG_CONFIG_HOME/urxvt/plugins (default
 * ~/.config/urxvt/plugins), see doc/lua-plugins.md for the API.
 *
 * The hooks reuse the HOOK_INVOKE/SHOULD_INVOKE call sites of the perl
 * interface, so this header provides the same macros and enums as
 * rxvtperl.h does for perl. The two interfaces are mutually exclusive.
 */

#ifndef RXVTLUA_H_
#define RXVTLUA_H_

#if ENABLE_LUA

#if ENABLE_PERL
# error "the perl and the lua plugin interfaces are mutually exclusive"
#endif

// Only checks a global flag array, so call sites of hooks that no plugin
// implements cost next to nothing.
#define SHOULD_INVOKE(htype) (rxvt_lua.should_invoke [htype])
#define HOOK_INVOKE(args) (rxvt_lua.L && rxvt_lua.invoke args)

enum data_type {
  DT_END,     // no further arguments
  DT_INT,
  DT_LONG,
  DT_STR,     // 0-terminated string
  DT_STR_LEN, // string + length
  DT_WCS_LEN, // wchar_t* + length
  DT_LCS_LEN, // long* + length
  DT_XEVENT,
};

enum hook_type {
# define def(sym) HOOK_ ## sym,
# include "hookinc.h"
# undef def
  HOOK_NUM,
};

struct lua_State;

// per terminal state, must be zero-initialised
struct rxvt_lua_term
{
  int ref; // registry reference of the lua terminal object, 0 if none
};

struct rxvt_lua_interp
{
  lua_State *L; // 0 unless at least one plugin was found
  uint8_t should_invoke[HOOK_NUM];

  // Loads the plugins on the first call and creates the lua object of
  // the terminal. Returns whether lua is active.
  bool init (rxvt_term *term);
  bool invoke (rxvt_term *term, int htype, ...);
};

extern struct rxvt_lua_interp rxvt_lua;

#endif

#endif
