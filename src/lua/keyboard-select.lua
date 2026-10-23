-- keyboard-select.lua - select and copy text with vi-like keys
--
-- A port of the keyboard-select perl extension
--   Author:  Bert Muennich
--   Website: http://www.github.com/muennich/urxvt-perls
--   License: GPLv2
--
-- ACTIVATE_KEY (M-Escape) starts the selection mode at the cursor, the
-- program is paused until it ends. SEARCH_KEY (unset by default) starts it
-- with a backward search. Then:
--
--   h/j/k/l, arrows    move the cursor left/down/up/right
--   0 ^ $ Home End     start, first non-blank, end of the line
--   w W b B e E        word motions
--   f F ; ,            jump to a character, repeat forwards/backwards
--   g G H M L          top/bottom of the scrollback, top/middle/bottom of
--                      the window
--   C-f C-b C-d C-u    scroll a page/half a page down/up
--   / ?                search forward/backward (case-insensitive unless the
--                      text contains upper case letters), n/N repeat,
--                      C-S-v in the search prompt pastes the clipboard
--                      In the prompt, C-a C-e (Home End) move the cursor
--                      to the start/end, Left Right by a character, C-u
--                      clears the text before the cursor, C-w removes the
--                      word before it
--   v V C-v            toggle normal/linewise/blockwise selection
--   y Return           copy the selection, Return quits afterwards
--   Y                  copy the selected lines, or the cursor line and quit
--   q Escape C-c       quit
--
-- The selection goes to PRIMARY, and to the CLIPBOARD as well if the
-- NRxvt.keyboard-select.clipboard resource is true. Keysym resources of
-- the perl extension keep working, e.g.
--
--   NRxvt.keysym.M-Escape: perl:keyboard-select:activate
--   NRxvt.keysym.M-s:      perl:keyboard-select:search
--
-- Copy or link this file into ~/.config/nrxvt/plugins to enable it.

local ACTIVATE_KEY = "M-Escape"
-- e.g. "M-s", which search.lua uses as well
local SEARCH_KEY = nil

-- character classes for the word motions, like \s, \w and the rest in the
-- regular expressions of the perl version
local SPACE, WORD, PUNCT = 0, 1, 2
local SPACE_RE, WORD_RE = nrxvt.regex ("^\\s"), nrxvt.regex ("^\\w")
-- search texts with upper case letters are case-sensitive
local UPPER_RE = nrxvt.regex ("[[:upper:]]")

-- the cursor of the search prompt is drawn reversed, the text isn't
local PROMPT_TEXT = { nrxvt.style { reverse = false } }
local PROMPT_CURSOR = { nrxvt.style { reverse = true } }

-- the keys of move_cursor, those in SCROLL_KEYS only with Control
local CURSOR_KEYS = { g = true, G = true, ["0"] = true, ["^"] = true, ["$"] = true, H = true, M = true, L = true }
local SCROLL_KEYS = { f = true, b = true, d = true, u = true }
local MOVE_TO_KEYS = { [";"] = true, [","] = true, w = true, W = true, b = true, B = true, e = true, E = true }

-- one UTF-8 encoded character, as pattern
local UTF8_CHAR = "[%z\1-\127\194-\244][\128-\191]*"

-- number of characters of an UTF-8 string
local function length (s)
  return select (2, s:gsub ("[^\128-\191]", ""))
end

-- logical lines, like the line objects of perl

local Line = {}
Line.__index = Line

-- the logical line that row is part of
local function line (t, row)
  local beg, last, len = t:line_bounds (row)
  return setmetatable ({ t = t, beg = beg, last = last, l = len, ncol = t:ncol () }, Line)
end

function Line:offset_of (row, col)
  return (row - self.beg) * self.ncol + col
end

function Line:coord_of (offset)
  -- the offset of an empty line's last cell is -1, perl's integer division
  -- maps it to its first row, and the cursor clamps the column
  if offset < 0 then return self.beg, 0 end
  return self.beg + math.floor (offset / self.ncol), offset % self.ncol
end

-- the text of the cells, one entry per cell
function Line:cells ()
  if not self.cell_list then
    local cells = {}
    for row = self.beg, self.last do
      for _, cell in ipairs (self.t:cells (row)) do
        cells[#cells + 1] = cell
      end
    end
    self.cell_list = cells
  end
  return self.cell_list
end

-- the character classes of the cells, the second cell of wide characters
-- belongs to the character
function Line:classes ()
  if not self.class_list then
    local classes = {}
    for i, cell in ipairs (self:cells ()) do
      if cell == "" then
        classes[i] = classes[i - 1] or SPACE
      elseif SPACE_RE:find (cell) then
        classes[i] = SPACE
      elseif WORD_RE:find (cell) then
        classes[i] = WORD
      else
        classes[i] = PUNCT
      end
    end
    self.class_list = classes
  end
  return self.class_list
end

-- the UTF-8 text of the line and the byte position each cell starts at
function Line:text ()
  local cells = self:cells ()
  local starts, pos = {}, 1
  for i, cell in ipairs (cells) do
    starts[i] = pos
    pos = pos + #cell
  end
  starts[#cells + 1] = pos
  return table.concat (cells), starts
end

-- the offset of the cell containing a byte position of Line:text
local function offset_at (starts, byte)
  local offset = 0
  while starts[offset + 2] and starts[offset + 2] <= byte do
    offset = offset + 1
  end
  return offset
end

-- the status area

local function status_area (t, ks, extra)
  local stat

  if ks.search ~= "" then
    -- the padding makes room for the cursor at the end of the text
    stat = ks.search .. string.rep (" ", t:ncol () - length (ks.search))
  else
    stat = ""
    if ks.select ~= "" then
      stat = "-V" .. (ks.select ~= "n" and ks.select:upper () or "") .. "- "
    end

    local top, view = t:top_row (), t:view_start ()
    if top == 0 then
      stat = stat .. "All"
    elseif view == top then
      stat = stat .. "Top"
    elseif view == 0 then
      stat = stat .. "Bot"
    else
      stat = stat .. string.format ("%2d%%", math.floor ((top - view) * 100 / top))
    end

    if extra then stat = extra .. " " .. stat end
  end

  -- a borderless one row overlay in the bottom right corner
  local len = length (stat)
  if not ks.overlay or ks.overlay_len ~= len then
    if ks.overlay then ks.overlay:close () end
    ks.overlay = t:new_overlay (-1, -1, len, 1, false)
    ks.overlay_len = len
  end

  ks.overlay:set (0, 0, stat, unpack (PROMPT_TEXT))
  if ks.search ~= "" then
    -- redraws the character at the cursor reversed, or a blank at the end
    local col = length (ks.search:sub (1, ks.search_cur))
    local cell = ks.search:match ("^" .. UTF8_CHAR, ks.search_cur + 1) or " "
    if col < len then ks.overlay:set (col, 0, cell, unpack (PROMPT_CURSOR)) end
  end
  ks.overlay:show ()
end

-- keeps the cursor in the window, the perl version does this on every
-- refresh, here the cursor only moves on key presses
local function show_cursor (t)
  local row = t:cursor ()
  local view, nrow = t:view_start (), t:nrow ()

  if row < view then
    t:view_start (row)
  elseif row >= view + nrow then
    t:view_start (row - nrow + 1)
  end
end

-- selection

-- the selected area, an exclusive end column; in blockwise mode the rows
-- are the first rows of logical lines and the columns are offsets
local function calc_span (t, ks)
  local cr, cc = t:cursor ()
  local br, bc, er, ec

  if ks.select == "b" then
    local cl, al = line (t, cr), line (t, ks.ar)
    br, bc = cl.beg, cl:offset_of (cr, cc)
    er, ec = al.beg, al:offset_of (ks.ar, ks.ac)
    if br > er then br, er = er, br end
    if bc > ec then bc, ec = ec, bc end
  elseif cr < ks.ar then
    br, bc, er, ec = cr, cc, ks.ar, ks.ac
  elseif cr > ks.ar then
    br, bc, er, ec = ks.ar, ks.ac, cr, cc
  else
    br, er = cr, cr
    if cc < ks.ac then bc, ec = cc, ks.ac else bc, ec = ks.ac, cc end
  end

  if ks.select == "l" then
    br, er = line (t, br).beg, line (t, er).last
    bc, ec = 0, t:ncol ()
  else
    ec = ec + 1
  end

  return br, bc, er, ec
end

local function toggle_select (t, ks, mode)
  if ks.select == mode then
    ks.select = ""
  else
    if ks.select == "" then
      ks.ar, ks.ac = t:cursor ()
    end
    ks.select = mode
  end

  status_area (t, ks)
end

-- an empty selection, which removes the selection highlight
local function clear_selection (t)
  t:selection_beg (1, 0)
  t:selection_end (1, 0)
end

-- copies the selection to PRIMARY (and CLIPBOARD)
local function copy (t, ks, time)
  local br, bc, er, ec = calc_span (t, ks)
  if ks.select == "l" then ec = line (t, er).l end

  t:selection_beg (br, bc)
  t:selection_end (er, ec)
  t:selection_make (ks.select == "b", time)

  local text = t:selection ()
  if ks.clipboard and text then
    t:set_selection (text, true)
  end
end

-- cursor movement

local function move_cursor (t, ks, key)
  local cr, cc = t:cursor ()
  local ln = line (t, cr)
  local top, nrow = t:top_row (), t:nrow ()

  if key == "k" and ln.beg > top then
    cr = ln.beg - 1
  elseif key == "j" and ln.last < nrow - 1 then
    cr = ln.last + 1
  elseif key == "h" and ks.offset > 0 then
    local offset = ln:offset_of (cr, cc) - 1
    -- skip the second cell of wide characters
    local cells = ln:cells ()
    while offset > 0 and cells[offset + 1] == "" do offset = offset - 1 end
    ks.offset = math.max (offset, 0)
    ks.dollar = 0
  elseif key == "l" and ks.offset < ln.l - 1 then
    local offset = ks.offset + 1
    local cells = ln:cells ()
    while offset < ln.l - 1 and cells[offset + 1] == "" do offset = offset + 1 end
    ks.offset = offset
  elseif key == "f" or key == "d" or key == "b" or key == "u" then
    local view = t:view_start ()
    local amount = (key == "d" or key == "u") and math.floor (nrow / 2) or nrow - 1
    if key == "b" or key == "u" then amount = -amount end

    -- move the cursor as far as the window could be scrolled
    local new = t:view_start (math.max (top, math.min (0, view + amount)))
    cr = math.max (top, math.min (nrow - 1, cr + new - view))
  elseif key == "g" then
    cr, ks.offset, ks.dollar = top, 0, 0
  elseif key == "G" then
    cr, ks.offset, ks.dollar = nrow - 1, 0, 0
  elseif key == "0" then
    ks.offset, ks.dollar = 0, 0
  elseif key == "^" then
    local cells, offset = ln:cells (), 0
    while cells[offset + 1] == " " or cells[offset + 1] == "\t" do offset = offset + 1 end
    ks.offset, ks.dollar = offset, 0
  elseif key == "$" then
    ks.dollar = ln:offset_of (cr, cc) + 1
    ks.offset = ln.l - 1
  elseif key == "H" then
    cr = t:view_start ()
  elseif key == "M" then
    cr = t:view_start () + math.floor (nrow / 2)
  elseif key == "L" then
    cr = t:view_start () + nrow - 1
  end

  ln = line (t, cr)
  local offset = (ks.dollar > 0 or ks.offset >= ln.l) and ln.l - 1 or ks.offset
  t:cursor (ln:coord_of (offset))

  status_area (t, ks)
end

-- Whether a word (or WORD, if big) starts at offset i, i.e. whether the
-- characters before and at i match the perl pattern \w[^\w\s]|\W\w|\s\S
-- (\s\S for WORDs).
local function starts_word (classes, i, big)
  local a, b = classes[i], classes[i + 1]
  if big then return a == SPACE and b ~= SPACE end
  return a ~= b and b ~= SPACE
end

-- Whether a word (or WORD) ends at offset i, the perl pattern
-- [^\w\s](?=\w)|\w(?=\W)|\S(?=\s|$) (\S(?=\s|$) for WORDs).
local function ends_word (classes, i, big)
  local a, b = classes[i + 1], classes[i + 2]
  if a == SPACE then return false end
  if big then return b == nil or b == SPACE end
  return b ~= a
end

-- f/F/;/, and the word motions. Unlike the perl version, they start from
-- the cursor rather than the column remembered for j/k.
local function move_to (t, ks, key)
  local cr, cc = t:cursor ()
  local ln = line (t, cr)
  local offset = ln:offset_of (cr, cc)
  local nrow = t:nrow ()
  local found

  if key == ";" or key == "," then
    local char = ks.move_char
    if not char then return end

    local cells = ln:cells ()
    if ks.move_dir * (key == "," and -1 or 1) > 0 then
      for i = offset + 1, ln.l - 1 do
        if cells[i + 1] == char then found = i break end
      end
    else
      for i = offset - 1, 0, -1 do
        if cells[i + 1] == char then found = i break end
      end
    end
  elseif key == "b" or key == "B" then
    -- the last word start before the cursor, or the start of the line,
    -- or the last word of the previous lines
    while true do
      local classes = ln:classes ()
      for i = offset - 1, 1, -1 do
        if starts_word (classes, i, key == "B") then found = i break end
      end
      if found then break end

      if offset > 0 then
        found = 0
        break
      end
      if ln.beg <= t:top_row () then break end

      ln = line (t, ln.beg - 1)
      offset = ln.l
    end
  elseif key == "e" or key == "E" then
    -- the next word end after the cursor, in the following lines too
    offset = offset + 1
    while true do
      local classes = ln:classes ()
      for i = offset, ln.l - 1 do
        if ends_word (classes, i, key == "E") then found = i break end
      end
      if found or ln.last + 1 >= nrow then break end

      ln = line (t, ln.last + 1)
      offset = 0
    end
  else
    -- w/W: the next word start, or the start of the next line
    local classes = ln:classes ()
    for i = offset + 1, ln.l - 1 do
      if starts_word (classes, i, key == "W") then found = i break end
    end

    if not found and ln.last + 1 < nrow then
      ln = line (t, ln.last + 1)
      found = 0
    end
  end

  if found then
    ks.dollar = 0
    ks.offset = found
    t:cursor (ln:coord_of (found))
  end
end

-- search

-- the search text as literal pattern, case-insensitive unless it contains
-- upper case
local function set_pattern (ks, text)
  if text ~= "" then
    ks.pattern = nrxvt.regex (nrxvt.regex_escape (text), UPPER_RE:find (text) and "" or "i")
  else
    ks.pattern = nil
  end
end

-- the start of the last match in text that ends before byte limit, matches
-- don't overlap like with perl's m//g
local function last_match (text, pattern, limit)
  local found
  for s, e in pattern:gfind (text) do
    if e >= limit then break end
    found = s
  end
  return found
end

local function find_next (t, ks, dir)
  if not ks.pattern then return false end
  dir = dir or ks.search_dir

  local pattern = ks.pattern

  local cr, cc = t:cursor ()
  local ln = line (t, cr)
  local offset = ln:offset_of (cr, cc)
  if dir > 0 then offset = offset + 1 end

  local text, starts = ln:text ()
  local byte

  if dir > 0 then
    byte = pattern:find (text, starts[math.min (offset, ln.l) + 1])
  else
    byte = last_match (text, pattern, starts[math.max (0, math.min (offset, ln.l)) + 1])
  end

  -- check the other lines with the plain row texts first, which is much
  -- cheaper than splitting them into cells, scrollbacks can be large
  local top, nrow = t:top_row (), t:nrow ()
  local row = dir > 0 and ln.last + 1 or ln.beg - 1

  while not byte and row >= top and row < nrow do
    local beg, last = t:line_bounds (row)
    local parts = {}
    for r = beg, last do parts[#parts + 1] = (t:line (r)) end

    if pattern:find (table.concat (parts)) then
      ln = line (t, row)
      text, starts = ln:text ()
      if dir > 0 then
        byte = pattern:find (text)
      else
        byte = last_match (text, pattern, math.huge)
      end
    end

    row = dir > 0 and last + 1 or beg - 1
  end

  if not byte then return false end

  ks.dollar = 0
  ks.offset = offset_at (starts, byte)
  t:cursor (ln:coord_of (ks.offset))
  status_area (t, ks)
  return true
end

-- activation

local function activate (t, search)
  local ks = {
    select = "", dollar = 0, move_to = false,
    search = "", search_dir = 1, search_mode = false,
    -- the number of bytes of ks.search before the prompt's cursor
    search_cur = 0,
    clipboard = t:resource_boolean ("keyboard-select.clipboard"),
    -- the selection is drawn like urxvt does it
    hl_sel = t:resource ("highlightColor") ~= nil,
  }

  if search then
    ks.search, ks.search_dir, ks.search_mode = "?", -1, true
    ks.search_cur = 1
  end

  ks.oldcr, ks.oldcc = t:cursor ()
  ks.srhcr, ks.srhcc = ks.oldcr, ks.oldcc
  ks.old_view_start = t:view_start ()
  -- the program is paused, so the cursor can move freely
  ks.old_pty_events = t:pty_events (nrxvt.EV_NONE)

  local ln = line (t, ks.oldcr)
  ks.offset = ln:offset_of (ks.oldcr, ks.oldcc)

  clear_selection (t)
  t.keyboard_select = ks

  if ks.offset >= ln.l then
    ks.offset = ln.l > 0 and ln.l - 1 or 0
    t:cursor (ln:coord_of (ks.offset))
  end

  show_cursor (t)
  status_area (t, ks)
  t:refresh ()
end

local function deactivate (t)
  local ks = t.keyboard_select

  clear_selection (t)
  if ks.overlay then ks.overlay:close () end

  t.keyboard_select = nil
  t:cursor (ks.oldcr, ks.oldcc)
  t:view_start (ks.old_view_start)
  t:pty_events (ks.old_pty_events)
  t:refresh ()
end

-- key handling

-- the byte count before the character preceding/following the cursor
local function char_before (ks)
  local i = ks.search_cur
  while i > 1 and ks.search:byte (i) >= 0x80 and ks.search:byte (i) < 0xc0 do i = i - 1 end
  return i - 1
end

local function char_after (ks)
  local _, e = ks.search:find ("^" .. UTF8_CHAR, ks.search_cur + 1)
  return e or ks.search_cur
end

-- replaces the text between the byte counts from and to (the first byte of
-- the search is the / or ? that opened the prompt) and puts the cursor at
-- the end of the replacement
local function search_replace (ks, from, to, text)
  ks.search = ks.search:sub (1, from) .. text .. ks.search:sub (to + 1)
  ks.search_cur = from + #text
end

-- adds text at the cursor and searches again from where the search started
local function search_append (t, ks, text)
  search_replace (ks, ks.search_cur, ks.search_cur, text)
  set_pattern (ks, ks.search:sub (2))
  t:cursor (ks.srhcr, ks.srhcc)
  find_next (t, ks)
  status_area (t, ks)
end

-- adds pasted text to the search like typed text, only its first line as
-- matches never span lines
local function search_paste (t, ks, text)
  -- the search might be over by the time the text arrives
  if not text or t.keyboard_select ~= ks or ks.search == "" then return end

  text = text:match ("^[^\r\n]*"):gsub ("%c", "")
  if text ~= "" then
    search_append (t, ks, text)
    t:refresh ()
  end
end

-- the keys of the search prompt
local function search_key (t, ks, ev, key, char, enter)
  if key == "Escape" then
    if ks.search_mode then return deactivate (t) end
    ks.search = ""
    status_area (t, ks)
  elseif key == "BackSpace" then
    if #ks.search == 1 then
      -- nothing left to delete, this ends the search
      ks.search = ""
      if ks.search_mode then return deactivate (t) end
    elseif ks.search_cur > 1 then
      search_replace (ks, char_before (ks), ks.search_cur, "")
    end
    status_area (t, ks)
  elseif ev.ctrl and key:lower () == "u" then
    -- clears the text before the cursor
    search_replace (ks, 1, ks.search_cur, "")
    status_area (t, ks)
  elseif ev.ctrl and key:lower () == "w" then
    -- removes the blanks and the word before the cursor
    local before = ks.search:sub (2, ks.search_cur)
    search_replace (ks, 1 + #before:gsub ("%s*%S*$", ""), ks.search_cur, "")
    status_area (t, ks)
  elseif key == "Home" or (ev.ctrl and key:lower () == "a") then
    ks.search_cur = 1
    status_area (t, ks)
  elseif key == "End" or (ev.ctrl and key:lower () == "e") then
    ks.search_cur = #ks.search
    status_area (t, ks)
  elseif key == "Left" then
    if ks.search_cur > 1 then ks.search_cur = char_before (ks) end
    status_area (t, ks)
  elseif key == "Right" then
    ks.search_cur = char_after (ks)
    status_area (t, ks)
  elseif enter then
    set_pattern (ks, ks.search:sub (2))
    ks.search = ""
    t:cursor (ks.srhcr, ks.srhcc)
    if not find_next (t, ks) then
      if ks.search_mode then return deactivate (t) end
      status_area (t, ks)
    end
  elseif ev.ctrl and ev.shift and key:lower () == "v" then
    -- pastes the clipboard
    t:selection_fetch (true, function (text) search_paste (t, ks, text) end, ev.time)
  elseif char then
    search_append (t, ks, char)
  end
end

local function key_press (t, ks, ev, keysym, str)
  -- printable ASCII keysyms are their characters, e.g. "$" for "dollar"
  local key = keysym >= 0x20 and keysym < 0x7f and string.char (keysym)
              or nrxvt.keysym_name (keysym) or ""
  local lower = key:lower ()
  local ctrl = ev.ctrl
  -- the typed text, without control characters (or Meta's escape prefix)
  local char = str ~= "" and not str:find ("%c") and str or nil
  local enter = key == "Return" or (ctrl and lower == "m")

  if ctrl and lower == "c" then
    deactivate (t)
  elseif ks.search ~= "" then
    search_key (t, ks, ev, key, char, enter)
  elseif ks.move_to then
    if key == "Escape" then
      ks.move_to = false
      status_area (t, ks)
    elseif char then
      ks.move_to = false
      ks.move_char = char
      move_to (t, ks, ";")
      status_area (t, ks)
    end
  elseif key == "Escape" or lower == "q" then
    deactivate (t)
  elseif lower == "y" or enter then
    local quit = false

    if key == "Y" and ks.select ~= "l" then
      quit = ks.select == ""
      toggle_select (t, ks, "l")
    end

    if ks.select ~= "" then
      copy (t, ks, ev.time)

      if lower == "y" then
        clear_selection (t)
        ks.select = ""
        status_area (t, ks)
      else
        quit = true
      end
    end

    if quit then deactivate (t) end
  elseif key == "V" then
    toggle_select (t, ks, "l")
  elseif key == "v" then
    toggle_select (t, ks, ctrl and "b" or "n")
  elseif key == "k" or key == "Up" then
    move_cursor (t, ks, "k")
  elseif key == "j" or key == "Down" then
    move_cursor (t, ks, "j")
  elseif key == "h" or key == "Left" then
    move_cursor (t, ks, "h")
  elseif key == "l" or key == "Right" then
    move_cursor (t, ks, "l")
  elseif key == "End" then
    move_cursor (t, ks, "$")
  elseif key == "Home" then
    move_cursor (t, ks, "^")
  elseif CURSOR_KEYS[key] or (ctrl and SCROLL_KEYS[key]) then
    move_cursor (t, ks, key)
  elseif lower == "f" then
    ks.move_to = true
    ks.move_dir = key == "F" and -1 or 1
    status_area (t, ks, key)
  elseif MOVE_TO_KEYS[key] then
    move_to (t, ks, key)
  elseif key == "/" or key == "?" then
    ks.search = key
    ks.search_cur = 1
    ks.search_dir = key == "?" and -1 or 1
    ks.srhcr, ks.srhcc = t:cursor ()
    status_area (t, ks)
  elseif lower == "n" then
    find_next (t, ks, ks.search_dir * (key == "N" and -1 or 1))
  end

  if t.keyboard_select then show_cursor (t) end
  t:refresh ()
end

nrxvt.bind (ACTIVATE_KEY, function (t)
  -- while active, the key is handled like any other (M-Escape is Escape)
  if t.keyboard_select then return false end
  activate (t)
end)

if SEARCH_KEY then
  nrxvt.bind (SEARCH_KEY, function (t)
    if t.keyboard_select then return false end
    activate (t, true)
  end)
end

local M = {}

-- the commands of the perl extension, for keysym resources
local COMMANDS = { activate = false, search = true }

function M.on_user_command (t, cmd)
  local search = COMMANDS[cmd:match ("^keyboard%-select:(.*)$")]
  if search == nil then return end
  if not t.keyboard_select then activate (t, search) end
  return true
end

function M.on_action (t, ext, action)
  if ext ~= "keyboard-select" or COMMANDS[action] == nil then return end
  if not t.keyboard_select then activate (t, COMMANDS[action]) end
  return true
end

function M.on_key_press (t, ev, keysym, str)
  local ks = t.keyboard_select
  if not ks then return end

  key_press (t, ks, ev, keysym, str)

  -- every key is consumed while selecting
  return true
end

-- nothing is sent to the program while selecting, a write that has to
-- wait for the pty would also resume its output
function M.on_tt_write (t)
  return t.keyboard_select ~= nil
end

-- draws the selection, the highlight is undone after the refresh
function M.on_refresh_begin (t)
  local ks = t.keyboard_select
  if not ks or ks.select == "" then return end

  local cr, cc = t:cursor ()
  local br, bc, er, ec = calc_span (t, ks)
  local hl, reverse_cursor

  if ks.hl_sel then
    -- highlightColor is not applied to the cursor
    hl, reverse_cursor = nrxvt.RS_Sel, false
  else
    hl, reverse_cursor = nrxvt.RS_RVid, ks.select ~= "l"
  end

  if ks.select == "b" then
    local co = line (t, cr):offset_of (cr, cc)
    local dollar = ks.dollar > 0 and co >= ks.dollar - 1

    local r = br
    while r <= er do
      local ln = line (t, r)
      if bc < ln.l then
        if dollar then ec = ln.l end
        local r0, c0 = ln:coord_of (bc)
        local r1, c1 = ln:coord_of (math.min (ec, ln.l))
        t:xor_span (r0, c0, r1, c1, hl)
      elseif r == cr then
        reverse_cursor = false
      end
      r = ln.last + 1
    end
  else
    t:xor_span (br, bc, er, ec, hl)
  end

  -- the reversed cursor would be invisible on reversed text
  if reverse_cursor then
    t:xor_span (cr, cc, cr, cc + 1, hl)
  end
end

return M
