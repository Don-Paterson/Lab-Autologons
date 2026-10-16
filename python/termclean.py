"""
termclean.py - strip terminal control codes from a stream of output.

Used by ubrun / cprun / vsx with --plain (automatic when the output is not a
console, e.g. called from another program): removes colours, window titles,
OSC 3008 context markers ("]3008;..."), bracketed-paste switches and the like,
and turns \\r\\n into \\n. Escape sequences split across reads are held back
until complete, so nothing is cut in half.
"""
import re

SEQ = re.compile(
    rb"\x1b\[[0-?]*[ -/]*[@-~]"              # CSI: colours, cursor, ?2004h ...
    rb"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC: titles, 3008 markers (BEL or ST)
    rb"|\x1b[()][0-9A-Za-z]"                 # charset selection
    rb"|\x1b[=>78DEHMc]"                     # keypad modes, save/restore, reset
)
# An escape sequence that has started but not finished at the end of a chunk
PARTIAL = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*|\][^\x07\x1b]*\x1b?|[()])?$")


CR = re.compile(rb"\r*\n\r*|\r+")


class Cleaner:
    def __init__(self):
        self.pending = b""
        self.at_line_start = True      # last byte written was a line break

    def __call__(self, data):
        data = self.pending + data
        self.pending = b""
        m = PARTIAL.search(data)
        if m and len(data) - m.start() < 4096:   # hold an unfinished sequence back
            self.pending = data[m.start():]
            data = data[:m.start()]
        if data.endswith(b"\r"):                 # maybe half of a \r\n
            self.pending = b"\r" + self.pending
            data = data[:-1]
        data = SEQ.sub(b"", data)
        data = data.replace(b"\x1b", b"")         # any stray ESC left over
        return self._lines(data)

    def _lines(self, data):
        # \r\n -> \n; a \r right after a line break is redundant (bash sends
        # "\r\n...\r"); any other lone \r (a redraw) becomes a line break.
        if self.at_line_start:
            data = data.lstrip(b"\r")
        data = CR.sub(b"\n", data)
        if data:
            self.at_line_start = data.endswith(b"\n")
        return data

    def flush(self):
        rest, self.pending = SEQ.sub(b"", self.pending).replace(b"\x1b", b""), b""
        return self._lines(rest)
