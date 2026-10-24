-- Export scrollback and screen rows as UTF-8 through a FIFO.
-- Copy or link this file into ~/.config/nrxvt/plugins to enable it, then
-- read a fresh snapshot with: cat /tmp/urxvt/urxvt-buffer-pipe-{PID}
-- PID is the terminal process ID, not the shell's process ID.

local api = nrxvt.api
local ffi = require "ffi"

ffi.cdef [[
  int getpid (void);
  int mkdir (const char *path, unsigned int mode);
  int mkfifo (const char *path, unsigned int mode);
  int open (const char *path, int flags, ...);
  int fcntl (int fd, int cmd, ...);
  long write (int fd, const void *buf, unsigned long count);
  int close (int fd);
  char *strerror (int errnum);
]]

-- These open flags and errno values differ between Linux and BSD/macOS.
assert (ffi.os == "Linux" or ffi.os == "BSD" or ffi.os == "OSX",
        "buffer-pipe requires Linux, BSD or macOS")
local O_NONBLOCK = ffi.os == "Linux" and 2048 or 4
local EAGAIN = ffi.os == "Linux" and 11 or 35
local EINTR, ENXIO, EEXIST = 4, 6, 17
local O_WRONLY, F_SETFD, FD_CLOEXEC = 1, 2, 1
local FIFO_DIR = "/tmp/urxvt"
local RETRY_DELAY, WRITE_DELAY = 0.1, 0.01
local WRITE_BUDGET = 65536

local function warn (operation, err)
  api.warn ("buffer-pipe: " .. operation .. ": " .. ffi.string (ffi.C.strerror (err)))
end

local function close_writer (s)
  if s.fd then ffi.C.close (s.fd) end
  s.fd, s.data, s.offset = nil, nil, nil
  s.timer:start (RETRY_DELAY, RETRY_DELAY)
end

local function serve (t, s)
  if not s.fd then
    -- A nonblocking open succeeds only when a reader is waiting. Never
    -- block the terminal's event loop while waiting for cat or another client.
    local fd = ffi.C.open (s.path, O_WRONLY + O_NONBLOCK)
    if fd < 0 then
      local err = ffi.errno ()
      if err ~= ENXIO and err ~= EINTR then
        warn ("open " .. s.path, err)
        s.timer:stop ()
      end
      return
    end
    s.fd = fd
    -- Do not let a program launched by the terminal keep a reader's FIFO open.
    if ffi.C.fcntl (fd, F_SETFD, ffi.cast ("int", FD_CLOEXEC)) < 0 then
      warn ("fcntl " .. s.path, ffi.errno ())
      close_writer (s)
      return
    end

    -- Capture once per reader so scrolling or resizing during a slow read
    -- cannot mix rows from different versions of the buffer. Wide-character
    -- continuation cells are already omitted by api.line.
    local lines, columns = {}, api.ncol (t)
    for row = api.top_row (t), api.nrow (t) - 1 do
      local text = api.line (t, row)
      -- Perl's ROW_t includes unused columns; api.line returns only text.
      -- Measure columns rather than UTF-8 bytes to preserve that padding.
      local padding = string.rep (" ", columns - api.col (t, row, #text + 1))
      lines[#lines + 1] = text:gsub ("\239\191\191", "") .. padding .. "\n"
    end
    s.data, s.offset = table.concat (lines), 0
    s.timer:start (WRITE_DELAY, WRITE_DELAY)
  end

  -- Bound work per callback and retain partial writes when a reader is slow.
  -- nrxvt ignores SIGPIPE, so a disconnected reader just makes write fail.
  local budget = WRITE_BUDGET
  local data = ffi.cast ("const char *", s.data)
  while s.offset < #s.data and budget > 0 do
    local count = math.min (#s.data - s.offset, budget, 4096)
    local written = tonumber (ffi.C.write (s.fd, data + s.offset, count))
    if written < 0 then
      local err = ffi.errno ()
      if err == EAGAIN or err == EINTR then return end
      close_writer (s)
      return
    elseif written == 0 then
      return
    end
    s.offset = s.offset + written
    budget = budget - written
  end
  -- Closing after the snapshot gives cat EOF, then the next reader gets a
  -- fresh snapshot rather than an endless stream of repeated buffer contents.
  if s.offset == #s.data then close_writer (s) end
end

api.on_start (function (t)
  if ffi.C.mkdir (FIFO_DIR, 448) < 0 then -- 0700, when creating the directory
    local err = ffi.errno ()
    if err ~= EEXIST then warn ("mkdir " .. FIFO_DIR, err); return end
  end

  local s = { path = FIFO_DIR .. "/urxvt-buffer-pipe-" .. ffi.C.getpid () }
  -- Refuse an existing path instead of replacing a file or another terminal's
  -- FIFO (several terminals can share a process when running under a daemon).
  if ffi.C.mkfifo (s.path, 384) < 0 then -- 0600
    warn ("mkfifo " .. s.path, ffi.errno ())
    return
  end
  t.buffer_pipe = s
  s.timer = api.timer (0, function () serve (t, s) end, RETRY_DELAY)
end)

api.on_destroy (function (t)
  local s = t.buffer_pipe
  if not s then return end
  s.timer:stop ()
  if s.fd then ffi.C.close (s.fd) end
  os.remove (s.path)
  t.buffer_pipe = nil
end)
