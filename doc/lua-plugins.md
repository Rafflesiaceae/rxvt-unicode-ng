# Lua plugins

The meson build embeds LuaJIT (`-Dlua=auto`, on whenever LuaJIT and PCRE2 are
found) as a lightweight replacement for the perl extensions of the autoconf
build.

Every `*.lua` file in `$XDG_CONFIG_HOME/urxvt/plugins` (by default
`~/.config/urxvt/plugins`) is loaded once at startup, in alphabetical order.
Files starting with a dot are skipped. Helper modules that should not be
loaded as plugins can live in `plugins/lib/` and be loaded with `require`.

Without any plugin file no Lua state is created at all. With plugins, only
the hooks they implement are ever called, so unused hooks cost nothing.

Four example plugins are installed to `share/urxvt/lua` (see `src/lua/`):

- `keyboard-select.lua` selects and copies text with vi-like keys (`M-Escape`),
  a port of the keyboard-select perl extension
- `links.lua` underlines URLs, opens them with Ctrl + click and lets you
  select them from the keyboard (`M-u`)
- `search.lua` searches incrementally through the whole scrollback (`M-s`)
- `scrollbar.lua` provides a 4px left scrollbar with a draggable proportional handle

Enable them by copying or linking them into the plugin directory, and change
their settings (keys, opener, ...) at the top of the files.

## Writing plugins

The implicit `nrxvt` global is available before plugins are loaded. No
`require` call is needed. A plugin returns a table of hook functions:

```lua
local M = {}

function M.on_start (t)
  nrxvt.warn ("terminal with " .. t:nrow () .. " rows started")
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

Renditions (colors and attributes) are 32-bit masks. `nrxvt.style` builds a
pair of masks, and the functions that take one apply
`rend = (rend & and_mask) | or_mask`:

```lua
local URL = { nrxvt.style { underline = true, fg = 4 } }
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
| `t:xor_span (r0, c0, r1, c1 [, mask])` | XORs `mask` (default `nrxvt.RS_RVid`) into the renditions from `(r0, c0)` to `(r1, c1)` (exclusive), the rows in between completely, like perl's `scr_xor_span`. Like `t:highlight`, only allowed in `on_refresh_begin` and undone after the redraw |
| `t:xor_rect (r0, c0, r1, c1 [, mask1 [, mask2]])` | the same for the columns `[c0, c1)` of the rows `r0` to `r1`, `mask2` (default `RS_RVid + RS_Uline`) goes to the trailing blanks but the first, like rectangular selections and perl's `scr_xor_rect` |
| `t:overlay (x, y, w, h)` | opens the overlay box (there is one per terminal), negative `x`/`y` count from the right/bottom, the border adds one cell on each side |
| `t:overlay_text (x, y, text [, and_mask, or_mask])` | writes into the overlay |
| `t:overlay_off ()` | closes the overlay |
| `t:new_overlay (x, y, w, h [, border [, and_mask, or_mask]])` | a new overlay object, see below |
| `t:new_bar (options)` | reserves an edge strip and returns a retained bar object, see below |
| `t:write (data)` | sends data to the program, as if typed |
| `t:feed (data)` | processes data as if the program had output it |
| `t:refresh ()` | schedules a redraw, needed after changes outside of hooks, e.g. in timers |
| `t:pty_events ([events])` | the events (`nrxvt.EV_READ`, `nrxvt.EV_WRITE`) urxvt waits for on the pty, changed first if given. `nrxvt.EV_NONE` pauses the program output until the returned old value is restored. Writes to the program that can't be sent at once (keys that are not consumed, `t:write`) resume it, consume them with `on_tt_write` while paused |
| `t:selection ([clipboard])` | the PRIMARY (or CLIPBOARD) selection text, or nil |
| `t:set_selection (text [, clipboard])` | sets and claims the selection |
| `t:selection_beg ([row, col])`, `t:selection_end (...)`, `t:selection_mark (...)` | the start, the (exclusive) end and the mark of the selection, set first if given. Like in perl, an end column 0 means the end of the previous row, and columns beyond the text of the row the whole row including its newline |
| `t:selection_make ([rect [, time]])` | selects the text between `selection_beg` and `selection_end` (a rectangle if `rect` is true) like the mouse does, and claims PRIMARY |
| `t:selection_grab ([clipboard [, time]])` | claims PRIMARY (or CLIPBOARD) with the current text, returns whether that worked |
| `t:selection_clear ([clipboard])` | forgets the PRIMARY text and removes the selection highlight (or forgets the CLIPBOARD text) |
| `t:selection_request ([clipboard [, time]])` | pastes PRIMARY (or CLIPBOARD) into the program |
| `t:selection_fetch (clipboard, fn [, time])` | requests PRIMARY (or CLIPBOARD) and calls `fn (text)` with it instead of pasting it, or `fn (nil)` if there is none. `fn` runs once the owner has answered, which may be right away. Returns `false` without requesting anything while another fetch of the terminal is pending. Pass the key or button event's `ev.time` as `time` where there is one. |
| `t:resource (name)` | the X resource `NRxvt.<name>` by default, or nil |
| `t:resource_boolean (name)` | the X resource as a boolean: true for `true`, `yes`, `on` and `1` (in any case), false otherwise, nil if it is not set |

The default X resource name and class are `nrxvt` and `NRxvt`. Use `NRxvt.<name>` for shared resource settings, or `nrxvt.<name>` for an instance named `nrxvt`. Builds may override these defaults with the Meson `res-name` and `res-class` options.

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

### Bars

Bars reserve pixels outside the text viewport. Create them in `on_init` so their reservations are included in initial character geometry. Runtime creation or closure keeps the current outer window size and adjusts text rows/columns as necessary on the next scheduled frame. Hidden bars keep their reservation and show terminal background. Bars remain registered even if their Lua references are garbage collected; `close` explicitly releases the reservation. All bars close when their terminal is destroyed.

```lua
function M.on_init(t)
  -- Horizontal bars own corners; nested parts inherit the bar's flow axis.
  t.status_bar = t:new_bar {
    edge = "bottom", thickness = 24, priority = 0,
    on_event = function(term, bar, ev)
      if ev.type == "button_press" and ev.button == 1 then
        nrxvt.warn("clicked " .. (ev.id or "the bar background"))
      end
    end,
  }
  t.status_bar:submit {
    bg = "background",
    children = {
      { id = "mode", size = { px = 80 }, text = "NORMAL" },
      { id = "title", size = { ratio = 3 }, text = "Terminal" },
      { id = "position", size = { ratio = 1 }, text = "Ready" },
    },
  }
end
```

`edge`, `thickness`, and `priority` are required and fixed for the bar's lifetime. Edges are `"top"`, `"bottom"`, `"left"`, and `"right"`. Thickness is an integer from 1 through 32767 pixels; total reservations must fit X11 geometry limits. Priority is a signed 32-bit integer: smaller numbers are closer to the outside, with creation order breaking ties. `visible` is an optional boolean, defaulting to true; `on_event` is an optional function. Top/bottom bars span the client width and own the corners. Left/right bars occupy the height between them. The independent native scrollbar, if enabled, occupies its own gutter between the corresponding side's bars and the text viewport.

The root of a submitted tree covers the bar. Each child requires a unique nonempty string `id` and `size = { px = n }` or `size = { ratio = r }`. Arrays determine order. Children may have nested `children` arrays; all descendants flow left-to-right in horizontal bars and top-to-bottom in vertical bars. Pixel sizes are nonnegative integers through 32767. Ratios are finite nonnegative numbers. Allocate pixels first, then divide the remainder by ratio. For example, in a 100px container, `4px`, `ratio=1`, and `ratio=3` allocate 4px, 24px, and 72px. Oversized pixel allocations retain their requested lengths and clip at their ancestors. Zero total ratio weight leaves the remainder as container background.

Nodes and the root accept `bg`, `fg`, and `text`. Colors are `"foreground"`, `"background"`, or terminal palette indices. Defaults are terminal background for rectangles and foreground for text. Text is single-line UTF-8, horizontally and vertically centered, unrotated, clipped, and rendered with terminal fonts. Parents paint before their children. No padding, wrapping, or images are provided. Text is limited to 65535 UTF-8 bytes per node; nesting is limited to 64 levels. Unknown fields, invalid numbers/text/colors, duplicate IDs, mixed sizing units, and sparse child arrays raise errors without changing the accepted scene.

`submit` always describes a complete replacement tree: omitted nodes disappear, omitted optional fields reset to defaults, and stable IDs preserve identity through reordering/reparenting. Mutating a table after submission has no effect until the next submission. C++ retains its own values and diffs each full tree in O(N); only differences schedule layout/paint. Reuse tables and avoid submitting when your relevant state has not changed. Drawing is deferred and coalesced by the existing refresh scheduler. A submission in `on_refresh_begin` appears in the same presentation. A bar-only update does not redraw terminal cells.

| Method | Description |
|---|---|
| `bar:submit(tree)` | Accept a complete tree and schedule incremental work. |
| `bar:visible([value])` | Return visibility, changing it first if a boolean is supplied; keep reserved space. |
| `bar:geometry()` | Return cached `x, y, width, height` in terminal client pixels, without an X query. Runtime reservation changes are reflected after the deferred geometry pass. |
| `bar:capture(ev)` | In this bar's button-press callback, capture the pointer for the press; return success. Wheel buttons cannot capture. |
| `bar:release()` | Release this bar's pointer capture. |
| `bar:close()` | Release capture, reservation, and resources. Repeated close is harmless. Other methods fail after closure. |

`on_event(t, bar, ev)` receives `button_press`, `button_release`, `motion`, `resize`, and `cancel`. Pointer events contain `id` (deepest hit part, or nil for root), bar-local `x, y`, part-local `local_x, local_y`, `x_root, y_root`, `state`, `time`, `shift`, `ctrl`, `meta`, and `button` for button events. Coordinates are pixels and have no terminal row/column interpretation. Events also provide bar `width` and `height`; cancellation provides `reason`. Event tables can be retained. Bar events never fall through to terminal selection, native scrollbar handling, text-window hooks, or application mouse reporting, regardless of the callback return value.

During capture, motion/release target the pressed part and retain out-of-bounds coordinates outside the window. A matching button release automatically ends capture after the callback; other buttons do not. Hiding/closing the bar, removing the captured node, unmapping/destroying the terminal, or a handler error cancels capture. A removed ID recreated later has a new identity. A failing callback is reported with a traceback and disabled. Callbacks may submit, hide, or close their own bar.

To enable the example scrollbar, copy or link `scrollbar.lua` into the plugin directory. Configure its thickness, minimum handle height, wheel step, and priority using the constants at the top. It uses terminal foreground/background, hides on the alternate screen or empty history while keeping its strip, and supports left-button handle dragging, page clicks, and three-line wheel steps while hovered. It never enables, disables, or uses the native scrollbar implementation; both can be active.

### Detecting alternate-screen applications

For a shortcut that should only run on the primary screen, query the screen
when the key is pressed:

```lua
nrxvt.bind ("C-S-K", function (t)
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
nrxvt.bind ("M-Up", function (t) t:prompt_jump (-1) end)
nrxvt.bind ("M-Down", function (t) t:prompt_jump (1) end)
```

Inside a hook, `t:prompt_marker ((t:cursor ()), true)` marks the cursor row.

The marker methods use the same row coordinates as `t:line`. Stored row numbers
can change or expire when output scrolls or the terminal resizes, so query them
again when needed. Markers are separate from cell renditions, so highlighting
and styling plugins do not overwrite them.

## The nrxvt global

| function | description |
|---|---|
| `nrxvt.bind (key, fn)` | calls `fn (t)` when `key` is pressed, using the keysym resource syntax (e.g. `"M-s"`, `"C-S-Up"`). The key is consumed unless `fn` returns `false`. As with keysym resources, extra modifiers are ignored. |
| `nrxvt.style {fg=, bg=, bold=, italic=, underline=, reverse=, blink=}` | returns `and_mask, or_mask`. Colors are indices (0-15 for the basic colors) or `"default"`. Attributes set to `true` are added, set to `false` are removed, and omitted ones are left alone. |
| `nrxvt.timer (after, fn [, repeat])` | calls `fn ()` after `after` seconds, then every `repeat` seconds. Returns a timer with `:start ([after [, repeat]])` and `:stop ()`. Active timers don't need to be referenced, and they never keep urxvt running. |
| `nrxvt.spawn (argv)` | starts a detached program. `argv` is an argument table, or a string run with `/bin/sh -c`. |
| `nrxvt.regex (pattern [, flags])` | compiles a perl compatible regular expression, see below |
| `nrxvt.regex_escape (s)` | escapes `s` to match literally, like perl's `quotemeta` or `\Q...\E` |
| `nrxvt.keysym_name (keysym)` | e.g. `"Return"` |
| `nrxvt.warn (msg)` | prints to stderr |
| `nrxvt.version`, `nrxvt.plugin_dir` | |
| `nrxvt.EV_NONE`, `EV_READ`, `EV_WRITE` | for `t:pty_events` |
| `nrxvt.RS_Bold`, `RS_Italic`, `RS_Blink`, `RS_RVid`, `RS_Uline`, `RS_Sel` | rendition bits, e.g. for `t:xor_span`. urxvt draws selections with `RS_Sel + RS_RVid`: reversed, or in `highlightColor`/`highlightTextColor` instead if those are set |

The LuaJIT `ffi` and `jit` modules are available as usual.

### Regular expressions

`nrxvt.regex` takes the place of perl's regexes, so patterns from perl
extension resources (e.g. `URxvt.matcher.pattern.1`) generally work
unchanged. It is
backed by PCRE2, which the lua plugin system always comes with. Patterns
and subjects are UTF-8 with Unicode semantics, like perl with character
strings: `\w`, `\s`, `\b`, `[[:upper:]]`, `\p{Lu}` and caseless matching
know non-ASCII characters, and `.` matches a whole character. Invalid UTF-8
in a subject never matches but is no error.

`flags` is a string of perl modifiers: `i` (caseless), `m` (`^` and `$`
match at newlines), `s` (`.` matches newlines) and `x` (extended). Invalid
patterns and flags raise an error, wrap them in `pcall` when they come from
resources or user input. Compile patterns once and reuse them, matching
uses PCRE2's JIT.

| method | description |
|---|---|
| `re:find (s [, init])` | `start, end, captures...` of the first match at or after byte `init` (default 1, negative counts from the end), or `nil`. Like `string.find`, positions are 1-based byte offsets, inclusive. |
| `re:match (s [, init])` | the captures of the first match, or the whole match if the pattern has no groups, or `nil`, like `string.match` |
| `re:gfind (s [, init])` | iterator over all non-overlapping matches, each returning what `re:find` would. Empty matches are handled like perl's `m//g`. |

Groups that did not take part in a match are `false`. Matching raises an
error when it hits PCRE2's match limit, e.g. with catastrophic
backtracking, instead of freezing the terminal.

```lua
local URL = nrxvt.regex ([[\bhttps?://[^\s<>"]+]], "i")

for s, e in URL:gfind (t:line (row)) do ... end

-- a literal search, caseless unless the query contains upper case
local query = nrxvt.regex (nrxvt.regex_escape (text),
                           nrxvt.regex ("\\p{Lu}"):find (text) and "" or "i")
```
