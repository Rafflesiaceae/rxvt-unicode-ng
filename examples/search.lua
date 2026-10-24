-- search.lua - incremental search through the whole scrollback
--
-- SEARCH_KEY (M-s) opens a search prompt at the bottom. Typing searches
-- backwards from the bottom for the text (case-insensitive unless it
-- contains upper case letters), all matches on screen are highlighted.
--
--   Up, C-p, M-s    previous (older) match
--   Down, C-n       next (newer) match
--   BackSpace       delete the last character
--   Return          leave the search, keeping the view
--   Escape, C-g     leave the search, restoring the view
--
-- Copy or link this file into ~/.config/nrxvt/plugins to enable it.

local api = nrxvt.api

local SEARCH_KEY = "M-s"

local MATCH = { api.style { reverse = true } }
local CURRENT = { api.style { fg = 0, bg = 11, reverse = false } }

-- the prompt overlay covers the last three rows (one plus its border)
local PROMPT_ROWS = 3

local UPPER = api.regex ("[[:upper:]]")

-- Sets the query, search.needle is the literal regex that is actually
-- searched for: smart case, i.e. case-insensitive unless the query
-- contains upper case letters.
local function set_query (search, query)
  search.query = query
  search.needle = query ~= "" and api.regex (api.regex_escape (query), UPPER:find (query) and "" or "i") or nil
end

-- number of characters of an UTF-8 string
local function length (s)
  return select (2, s:gsub ("[^\128-\191]", ""))
end

-- the last match in row starting before byte `before` (exclusive), or nil
local function last_in_row (t, search, row, before)
  local text = api.line (t, row)
  local query = search.needle
  local found
  local pos = 1

  while true do
    local s = query:find (text, pos)
    if not s or s >= before then break end
    found = s
    pos = s + 1
  end

  return found
end

-- searches older rows, starting with the match before (row, byte)
local function find_older (t, search, row, byte)
  for r = row, api.top_row (t), -1 do
    local s = last_in_row (t, search, r, r == row and byte or math.huge)
    if s then return r, s end
  end
end

-- searches newer rows, starting with the match after (row, byte)
local function find_newer (t, search, row, byte)
  for r = row, api.nrow (t) - 1 do
    local s = search.needle:find ((api.line (t, r)), r == row and byte + 1 or 1)
    if s then return r, s end
  end
end

local function draw_prompt (t, search)
  local status = ""
  if search.query ~= "" and not search.row then
    status = "[no match]"
  end

  local width = api.ncol (t) - 2
  local text = "search: " .. search.query
  local pad = width - length (text) - #status
  if pad < 1 then
    -- keep the end of long queries visible
    text = "search: <" .. search.query:sub (2 - pad)
    pad = 1
  end

  api.overlay_text (t, 0, 0, text .. string.rep (" ", pad) .. status)
end

-- scrolls so the current match is visible, if it is not already
local function show_match (t, search)
  if not search.row then return end

  local view = api.view_start (t)
  local nrow = api.nrow (t)

  if search.row < view or search.row >= view + nrow - PROMPT_ROWS then
    api.view_start (t, search.row - math.floor (nrow / 2))
  end
end

local function update (t, search, row, s)
  search.row, search.byte = row, s
  show_match (t, search)
  draw_prompt (t, search)
  api.refresh (t)
end

-- searches for the query from scratch, or from the current match when it
-- was only extended, so the match only moves when it has to
local function research (t, search)
  if search.query == "" then
    return update (t, search, nil, nil)
  end

  local row, s
  if search.row then
    row, s = find_older (t, search, search.row, search.byte + 1)
  end
  if not row then
    row, s = find_older (t, search, api.nrow (t) - 1, math.huge)
  end

  update (t, search, row, s)
end

local function stop (t, search, restore)
  if restore then api.view_start (t, search.view) end
  api.overlay_off (t)
  t.search = nil
  api.refresh (t)
end

-- moves to the previous or next match
local function step (t, search, older)
  if search.query == "" or not search.row then return end

  local row, s
  if older then
    row, s = find_older (t, search, search.row, search.byte)
  else
    row, s = find_newer (t, search, search.row, search.byte)
  end

  -- stay on the last match when there is no further one
  if row then update (t, search, row, s) end
end

api.bind (SEARCH_KEY, function (t)
  local search = t.search
  if search then
    return step (t, search, true)
  end

  search = { view = api.view_start (t) }
  set_query (search, "")
  t.search = search
  api.overlay (t, 0, -1, api.ncol (t) - 2, 1)
  draw_prompt (t, search)
  api.refresh (t)
end)

api.on_key_press (function (t, ev, keysym, str)
  local search = t.search
  if not search then return end

  local key = api.keysym_name (keysym)

  if key == "Escape" or (ev.ctrl and key == "g") then
    stop (t, search, true)
  elseif key == "Return" or key == "KP_Enter" then
    stop (t, search, false)
  elseif key == "Up" or (ev.ctrl and key == "p") then
    step (t, search, true)
  elseif key == "Down" or (ev.ctrl and key == "n") then
    step (t, search, false)
  elseif key == "BackSpace" then
    -- remove the last UTF-8 character
    set_query (search, (search.query:gsub ("[%z\1-\127\194-\244][\128-\191]*$", "")))
    research (t, search)
  elseif str ~= "" and not ev.ctrl and not ev.meta and not str:find ("%c") then
    set_query (search, search.query .. str)
    research (t, search)
  end

  -- every key is consumed while searching
  return true
end)

-- highlights the matches on screen
api.on_refresh_begin (function (t)
  local search = t.search
  if not search or search.query == "" then return end

  local query = search.needle
  local view = api.view_start (t)

  for row = view, view + api.nrow (t) - 1 - PROMPT_ROWS do
    for s, e in query:gfind ((api.line (t, row))) do
      local style = (row == search.row and s == search.byte) and CURRENT or MATCH
      api.highlight (t, row, api.col (t, row, s), api.col (t, row, e + 1), unpack (style))
    end
  end
end)

-- the screen size changed, the prompt has to be recreated
api.on_size_change (function (t)
  local search = t.search
  if search then
    api.overlay (t, 0, -1, api.ncol (t) - 2, 1)
    draw_prompt (t, search)
  end
end)
