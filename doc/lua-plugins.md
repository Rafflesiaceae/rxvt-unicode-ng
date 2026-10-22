# Lua plugins

The meson build embeds LuaJIT (`-Dlua=auto`, on whenever LuaJIT is found) as
a lightweight replacement for the perl extensions of the autoconf build.

Every `*.lua` file in `$XDG_CONFIG_HOME/urxvt/plugins` (by default
`~/.config/urxvt/plugins`) is loaded once at startup, in alphabetical order.
Files starting with a dot are skipped. Helper modules that should not be
loaded as plugins can live in `plugins/lib/` and be loaded with `require`.

Without any plugin file no Lua state is created at all. With plugins, only
the hooks they implement are ever called, so unused hooks cost nothing.

Two example plugins are installed to `share/urxvt/lua` (see `src/lua/`):

- `links.lua` underlines URLs, opens them with Ctrl + click and lets you
  select them from the keyboard (`M-u`)
- `search.lua` searches incrementally through the whole scrollback (`M-s`)

Enable them by copying or linking them into the plugin directory, and change
their settings (keys, opener, ...) at the top of the files.

## Writing plugins

A plugin returns a table of hook functions:

```lua
local urxvt = require "urxvt"

local M = {}

function M.on_start (t)
  urxvt.warn ("terminal with " .. t:nrow () .. " rows started")
end

-- typing "!" rings the bell instead of sending it
function M.on_key_press (t, ev, keysym, str)
  if str == "!" then
    t:feed ("\a")
    return true
  end
end

return M
```

Hooks are called with the terminal object `t` followed by the hook
arguments. If a hook returns a true value, the event counts as consumed:
the plugins after it are skipped, and for most hooks urxvt skips its own
handling too, e.g. the key is not sent to the program.

A hook that raises an error is reported on stderr once, with a traceback,
and is then disabled.

The terminal object is a table, so plugins can keep per-terminal state in
it. Prefix the fields with the plugin name to avoid clashes, e.g.
`t.search = {...}`. Once the terminal is destroyed, all methods raise an
error.

### Rows and columns

Rows are numbered relative to the top of the screen. Row 0 is the first row
of the screen, and `t:nrow () - 1` is the last one. Negative rows are in the
scrollback, down to `t:top_row ()`. The window shows the rows from
`t:view_start ()` (which is 0 or negative) to `t:view_start () + t:nrow () - 1`.

Columns start at 0. The text of a row is UTF-8, so byte offsets and columns
differ for non-ASCII text and wide characters. `t:col (row, byte)` maps a
byte offset to a column.

### Renditions

Renditions (colors and attributes) are 32-bit masks. `urxvt.style` builds a
pair of masks, and the functions that take one apply
`rend = (rend & and_mask) | or_mask`:

```lua
local URL = { urxvt.style { underline = true, fg = 4 } }
t:rend (row, c0, c1, unpack (URL))
```

Build styles once at load time, not in hooks.

## Hooks

The hooks are the ones of the perl interface (see `urxvtperl(3)`). Their
arguments are listed after `t`. X events (`ev`) are tables with `type`,
`window` and `send_event`. Key, button and motion events also have `x`, `y`,
`x_root`, `y_root`, `row` (absolute, like `t:line`), `col`, `state`, `time`,
`shift`, `ctrl` and `meta`, plus `keycode` or `button`.

| hook | arguments | notes |
|---|---|---|
| `on_init` | | before the window exists |
| `on_start` | | the window and the program are running |
| `on_destroy` | | the terminal is about to go away |
| `on_reset` | | the terminal was reset |
| `on_child_start` | pid | |
| `on_child_exit` | status | |
| `on_key_press` | ev, keysym, str | `str` is what would be sent to the program |
| `on_key_release` | ev, keysym | |
| `on_button_press` / `on_button_release` | ev | |
| `on_motion_notify` | ev | enables pointer motion events without pressed buttons |
| `on_focus_in` / `on_focus_out` | | |
| `on_line_update` | row | a changed logical line (starting at row, possibly wrapped) is about to be shown, the place for `t:rend` |
| `on_refresh_begin` / `on_refresh_end` | | around every redraw, `t:highlight` works in `on_refresh_begin` |
| `on_view_change` | view_start | the view was scrolled |
| `on_screen_change` | screen | after switching screens: 0 for primary, 1 for alternate; also fires when a hard reset returns to primary. Repeated requests for the same screen do not fire it. This is a notification and cannot cancel the switch. |
| `on_scroll_back` | lines, top_row | lines were moved into the scrollback |
| `on_add_lines` | text | text output by the program, return true to drop it |
| `on_tt_write` | data | data sent to the program, return true to drop it |
| `on_tt_paste` | data | data pasted into the program, return true to drop it |
| `on_osc_seq` | op, args | operating system commands, return true to consume |
| `on_bell` | | |
| `on_size_change` | width, height | in pixels |
| `on_sel_make` / `on_sel_grab` | time | a selection was made / is about to be claimed |
| `on_sel_extend` | | a selection is extended by clicks, return true to suppress it |
| `on_configure_notify` / `on_map_notify` / `on_unmap_notify` / `on_property_notify` / `on_client_message` / `on_x_event` | ev | |

## Terminal methods

| method | description |
|---|---|
| `t:nrow ()`, `t:ncol ()` | screen size in characters |
| `t:top_row ()` | row of the oldest scrollback line |
| `t:view_start ([row])` | first row in the window, scrolls there first if `row` is given |
| `t:current_screen ()` | 0 for the primary screen, 1 for the alternate screen; reads urxvt's existing state directly, without polling or system calls |
| `t:prompt_marker (row [, marked])` | whether a row has a prompt marker; pass a boolean to set or clear it |
| `t:prompt_markers ()` | table of marked row numbers, oldest first, including visible rows |
| `t:prompt_jump (direction)` | jumps to the previous marker for negative directions, the next for positive directions, or does nothing for zero; returns `view_start`. After the newest marker it returns to the live screen. Navigation does nothing on the alternate screen. |
| `t:cursor ([row, col])` | cursor `row, col`, moves the cursor first if `row` and `col` are given. Rows in the scrollback are allowed (like perl's `screen_cur`), pause the program with `t:pty_events` while the cursor is there, as its output would go there too |
| `t:focus ()` | whether the window has the focus |
| `t:font_size ()` | `width, height` of a character cell in pixels |
| `t:window ()` | X window id |
| `t:line (row)` | `text, wrapped`, where `wrapped` tells whether the line continues on the next row |
| `t:col (row, byte)` | column of the character at a 1-based byte offset of `t:line (row)` |
| `t:line_bounds (row)` | `beg, end, len` of the logical line that `row` is part of (it may be wrapped over several rows), `len` in cells. Offsets into it are `(row - beg) * t:ncol () + col`, like perl's line objects |
| `t:cells (row)` | table with the UTF-8 text of each cell of a row, column `col` at index `col + 1`, `""` for the second column of wide characters. Rows that continue on the next row have `t:ncol ()` cells, so the cells of the rows `beg` to `end` together are the `len` cells of the logical line |
| `t:rend (row, c0, c1, and_mask, or_mask)` | changes the rendition of columns `[c0, c1)` until the line changes again |
| `t:highlight (row, c0, c1, and_mask, or_mask)` | like `t:rend`, but only for the current redraw (only allowed in `on_refresh_begin`) |
| `t:xor_span (r0, c0, r1, c1 [, mask])` | XORs `mask` (default `urxvt.RS_RVid`) into the renditions from `(r0, c0)` to `(r1, c1)` (exclusive), the rows in between completely, like perl's `scr_xor_span`. Like `t:highlight`, only allowed in `on_refresh_begin` and undone after the redraw |
| `t:xor_rect (r0, c0, r1, c1 [, mask1 [, mask2]])` | the same for the columns `[c0, c1)` of the rows `r0` to `r1`, `mask2` (default `RS_RVid + RS_Uline`) goes to the trailing blanks but the first, like rectangular selections and perl's `scr_xor_rect` |
| `t:overlay (x, y, w, h)` | opens the overlay box (there is one per terminal), negative `x`/`y` count from the right/bottom, the border adds one cell on each side |
| `t:overlay_text (x, y, text [, and_mask, or_mask])` | writes into the overlay |
| `t:overlay_off ()` | closes the overlay |
| `t:new_overlay (x, y, w, h [, border [, and_mask, or_mask]])` | a new overlay object, see below |
| `t:write (data)` | sends data to the program, as if typed |
| `t:feed (data)` | processes data as if the program had output it |
| `t:refresh ()` | schedules a redraw, needed after changes outside of hooks, e.g. in timers |
| `t:pty_events ([events])` | the events (`urxvt.EV_READ`, `urxvt.EV_WRITE`) urxvt waits for on the pty, changed first if given. `urxvt.EV_NONE` pauses the program output until the returned old value is restored. Writes to the program that can't be sent at once (keys that are not consumed, `t:write`) resume it, consume them with `on_tt_write` while paused |
| `t:selection ([clipboard])` | the PRIMARY (or CLIPBOARD) selection text, or nil |
| `t:set_selection (text [, clipboard])` | sets and claims the selection |
| `t:selection_beg ([row, col])`, `t:selection_end (...)`, `t:selection_mark (...)` | the start, the (exclusive) end and the mark of the selection, set first if given. Like in perl, an end column 0 means the end of the previous row, and columns beyond the text of the row the whole row including its newline |
| `t:selection_make ([rect [, time]])` | selects the text between `selection_beg` and `selection_end` (a rectangle if `rect` is true) like the mouse does, and claims PRIMARY |
| `t:selection_grab ([clipboard [, time]])` | claims PRIMARY (or CLIPBOARD) with the current text, returns whether that worked |
| `t:selection_clear ([clipboard])` | forgets the PRIMARY text and removes the selection highlight (or forgets the CLIPBOARD text) |
| `t:selection_request ([clipboard [, time]])` | pastes PRIMARY (or CLIPBOARD) into the program |
| `t:resource (name)` | the X resource `URxvt.<name>`, or nil |
| `t:resource_boolean (name)` | the X resource as a boolean: true for `true`, `yes`, `on` and `1` (in any case), false otherwise, nil if it is not set |

The optional `time` arguments are X event times, e.g. `ev.time` of a key
event, and default to `CurrentTime`.

### Overlays

`t:overlay` shows a single box with a border, like urxvt's own popups.
`t:new_overlay` creates overlay objects like the perl `overlay` method: any
number of them, with or without border, and with their own colors. They
start hidden, `x`/`y` are window columns/rows, negative ones count from the
right/bottom (`-1, -1` is the bottom right corner), and the position follows
size changes. The border takes another cell on each side.

| method | description |
|---|---|
| `ov:set (x, y, text [, and_mask, or_mask])` | writes text at a cell inside the border, the masks change the default rendition of the overlay, without them the cells keep their rendition |
| `ov:show ()` | shows it on top of the other overlays |
| `ov:hide ()` | |
| `ov:close ()` | hides it and frees it, it can't be used afterwards |

Shown overlays stay visible until they are hidden or closed, even without
references. Hidden ones are freed when they are garbage collected, and all
of them when the terminal goes away.

```lua
-- a one line status box in the bottom right corner, without border
local status = t:new_overlay (-1, -1, 12, 1, false)
status:set (0, 0, "-- SELECT --")
status:show ()
```

### Detecting alternate-screen applications

For a shortcut that should only run on the primary screen, query the screen
when the key is pressed:

```lua
local urxvt = require "urxvt"

urxvt.bind ("C-S-K", function (t)
  -- Leave the key to the application while the alternate screen is active.
  if t:current_screen () == 1 then return false end
  t:prompt_jump (-1)
end)
```

Plugins that need to react as soon as the screen changes can implement
`on_screen_change (t, screen)` instead. No timer, process inspection, or shell
integration is needed. The hook runs after urxvt has updated its screen state,
so `t:current_screen ()` already returns the new value.

This reliably reports primary versus alternate screen, not whether an arbitrary
program is a fullscreen TUI. Applications can draw a TUI on the primary screen,
and multiplexers such as tmux can keep the outer terminal on the alternate
screen even when an inner pane shows a shell prompt. Disabling secondary-screen
storage does not change the reported mode; the value follows urxvt's screen
mode requests.

### Prompt markers

Prompt markers are detected on Return after nonempty commands with conventional
`$ `, `# `, `% ` or `> ` prompts. Ctrl+PageUp and Ctrl+PageDown navigate them.
Markers follow their lines through scrollback and resizing; fully clearing a
line removes its marker. Commands without intervening output share the latest
marker. Detection skips the alternate screen. Plugins can mark other prompt
formats explicitly, for example from `on_osc_seq`, and use the same navigation:

```lua
-- Add alternative shortcuts for the built-in prompt navigation.
urxvt.bind ("M-Up", function (t) t:prompt_jump (-1) end)
urxvt.bind ("M-Down", function (t) t:prompt_jump (1) end)
```

Inside a hook, `t:prompt_marker ((t:cursor ()), true)` marks the cursor row.

The marker methods use the same row coordinates as `t:line`. Stored row numbers
can change or expire when output scrolls or the terminal resizes, so query them
again when needed. Markers are separate from cell renditions, so highlighting
and styling plugins do not overwrite them.

## The urxvt module

| function | description |
|---|---|
| `urxvt.bind (key, fn)` | calls `fn (t)` when `key` is pressed, using the keysym resource syntax (e.g. `"M-s"`, `"C-S-Up"`). The key is consumed unless `fn` returns `false`. As with keysym resources, extra modifiers are ignored. |
| `urxvt.style {fg=, bg=, bold=, italic=, underline=, reverse=, blink=}` | returns `and_mask, or_mask`. Colors are indices (0-15 for the basic colors) or `"default"`. Attributes set to `true` are added, set to `false` are removed, and omitted ones are left alone. |
| `urxvt.timer (after, fn [, repeat])` | calls `fn ()` after `after` seconds, then every `repeat` seconds. Returns a timer with `:start ([after [, repeat]])` and `:stop ()`. Active timers don't need to be referenced, and they never keep urxvt running. |
| `urxvt.spawn (argv)` | starts a detached program. `argv` is an argument table, or a string run with `/bin/sh -c`. |
| `urxvt.keysym_name (keysym)` | e.g. `"Return"` |
| `urxvt.warn (msg)` | prints to stderr |
| `urxvt.version`, `urxvt.plugin_dir` | |
| `urxvt.EV_NONE`, `EV_READ`, `EV_WRITE` | for `t:pty_events` |
| `urxvt.RS_Bold`, `RS_Italic`, `RS_Blink`, `RS_RVid`, `RS_Uline`, `RS_Sel` | rendition bits, e.g. for `t:xor_span`. urxvt draws selections with `RS_Sel + RS_RVid`: reversed, or in `highlightColor`/`highlightTextColor` instead if those are set |

The LuaJIT `ffi` and `jit` modules are available as usual.
