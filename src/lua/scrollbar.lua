-- A reserved left scrollbar built entirely from the public bar API.
local THICKNESS = 4
local MIN_HANDLE = 20
local WHEEL_LINES = 3
local PRIORITY = 0

local M = {}
local floor, min, max = math.floor, math.min, math.max

local function round(n) return floor(n + 0.5) end
local function clamp(n, low, high) return max(low, min(high, n)) end

local function sync(t)
  local s = t.lua_scrollbar
  if not s then return end
  local _, _, _, length = s.bar:geometry()
  local history, rows = max(0, -t:top_row()), t:nrow()
  local shown = t:current_screen() == 0 and history > 0 and length > 0
  s.bar:visible(shown)
  if not shown then
    s.grab = nil
    return
  end

  local handle = min(length, max(MIN_HANDLE, round(length * rows / (rows + history))))
  local travel = length - handle
  local start = round(travel * (clamp(t:view_start(), -history, 0) + history) / history)
  s.history, s.rows, s.length, s.handle, s.travel, s.start = history, rows, length, handle, travel, start
  -- Complete trees are cheap here: reuse three stable nodes and submit only
  -- when their final pixel geometry changes, even while history keeps growing.
  if start ~= s.last_start or handle ~= s.last_handle or length ~= s.last_length then
    s.tree.children[1].size.px = start
    s.tree.children[2].size.px = handle
    s.tree.children[3].size.px = length - start - handle
    s.bar:submit(s.tree)
    s.last_start, s.last_handle, s.last_length = start, handle, length
  end
end

local function input(t, bar, ev)
  local s = t.lua_scrollbar
  if ev.type == "cancel" then s.grab = nil; return end
  if ev.type == "resize" then sync(t); return end
  -- Use current history and track geometry if output/resize arrived before
  -- the next scheduled frame; dragging never uses a stale scroll range.
  sync(t)
  if not bar:visible() then return end
  if ev.type == "button_press" then
    if ev.button == 4 or ev.button == 5 then
      t:view_start(t:view_start() + (ev.button == 4 and -WHEEL_LINES or WHEEL_LINES))
    elseif ev.button == 1 then
      if ev.y >= s.start and ev.y < s.start + s.handle then
        if s.travel > 0 and bar:capture(ev) then s.grab = ev.y - s.start end
      else
        t:view_start(t:view_start() + (ev.y < s.start and -s.rows or s.rows))
      end
    end
  elseif ev.type == "motion" and s.grab then
    if s.travel > 0 then
      s.grab = min(s.grab, s.handle - 1)
      local position = clamp(ev.y - s.grab, 0, s.travel)
      local row = -s.history + round(s.history * position / s.travel)
      if row ~= t:view_start() then t:view_start(row) end
    end
  elseif ev.type == "button_release" and ev.button == 1 then
    s.grab = nil
    bar:release()
  end
end

function M.on_init(t)
  local s = {
    tree = { bg = "background", children = {
      { id = "before", size = { px = 0 } },
      { id = "handle", size = { px = 0 }, bg = "foreground" },
      { id = "after", size = { px = 0 } },
    } },
  }
  t.lua_scrollbar = s
  s.bar = t:new_bar { edge = "left", thickness = THICKNESS, priority = PRIORITY,
                       visible = false, on_event = input }
end

-- One tuple/geometry calculation per refresh covers resets and explicit
-- scrollback clearing as well as ordinary output, without a polling timer.
M.on_start = sync
M.on_refresh_begin = sync
M.on_screen_change = sync
M.on_reset = sync

return M
