// Detection and navigation of submitted shell prompts.
#include "../config.h"
#include "rxvt.h"

// Like Exoterm, recognise a command after a conventional shell prompt.
// Work on the whole logical line so wrapped commands mark their start.
void
rxvt_term::scr_mark_prompt () noexcept
{
  if (current_screen != PRIMARY)
    return;

  int first = screen.cur.row;
  int last = first;
  while (first > top_row && ROW(first - 1).is_longer ())
    first--;
  while (last < nrow - 1 && ROW(last).is_longer ())
    last++;

  bool prompt = false;
  bool command = false;
  text_t prev = 0;

  for (int row = first; row <= last; row++)
    {
      line_t &line = ROW(row);
      for (int col = 0; col < min (int (line.l), ncol); col++)
        {
          text_t ch = line.t[col];
          if (ch == ' ' && (prev == '$' || prev == '#' || prev == '%' || prev == '>'))
            {
              prompt = true;
              command = false;
            }
          else if (prompt && ch != ' ' && ch != '\t' && ch != 0 && ch != NOCHAR)
            command = true;
          prev = ch;
        }
    }

  if (!command)
    return;

  // Keep only the latest command in a run with no intervening output.
  for (int row = first - 1; row >= top_row; row--)
    if (ROW(row).f & LINE_PROMPT)
      {
        int end = row;
        while (end < first - 1 && ROW(end).is_longer ())
          end++;

        for (int r = end + 1; r < first; r++)
          {
            line_t &line = ROW(r);
            for (int col = 0; col < min (int (line.l), ncol); col++)
              if (line.t[col] != ' ' && line.t[col] != '\t'
                  && line.t[col] != 0 && line.t[col] != NOCHAR)
                goto has_output;
          }

        ROW(row).f &= ~LINE_PROMPT;
        break;
      }

has_output:
  ROW(first).f |= LINE_PROMPT;
}

// Negative directions visit older markers; positive directions visit
// newer ones, returning to the live screen after the newest marker.
bool
rxvt_term::scr_prompt_jump (int direction) noexcept
{
  if (current_screen != PRIMARY || !direction)
    return false;

  int step = direction < 0 ? -1 : 1;
  for (int row = view_start + step; IN_RANGE_EXC (row, top_row, 1); row += step)
    if (ROW(row).valid () && (ROW(row).f & LINE_PROMPT))
      return scr_changeview (row);

  return direction > 0 ? scr_changeview (0) : false;
}
