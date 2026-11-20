"""Decoder for djay's TSAF binary archive format (reverse-engineered)."""
import struct


class TSAFError(Exception):
    pass


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0
        self.strings = []
        self.objects = []

    def align(self, n):
        r = self.p % n
        if r:
            self.p += n - r

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def cstr(self):
        end = self.d.index(b"\x00", self.p)
        s = self.d[self.p:end].decode("utf-8", "replace")
        self.p = end + 1
        return s

    def num(self, fmt, size):
        self.align(size)
        v = struct.unpack_from("<" + fmt, self.d, self.p)[0]
        self.p += size
        return v

    def value(self):
        t = self.u8()
        if t == 0x00:
            return _END
        if t == 0x08:
            s = self.cstr()
            self.strings.append(s)
            return s
        if t == 0x05:
            return self.strings[self.u8()]
        if t == 0x06:
            return self.strings[self.num("H", 2)]
        if t == 0x07:
            return self.strings[self.num("I", 4)]
        if t == 0x2B:  # object
            cls = self.value()
            obj = {"_class": cls}
            if not self.objects:
                self.objects.append(obj)
            while True:
                v = self.value()
                if v is _END:
                    return obj
                k = self.value()
                obj[k] = v
        if t == 0x02:  # back-reference to an earlier non-string object (e.g. date)
            i = self.u8()
            return self.objects[i] if i < len(self.objects) else None
        if t in (0x0A, 0x0B, 0x0C, 0x1A):  # arrays / sets
            n = self.num("I", 4)
            return [self.value() for _ in range(n)]
        if t == 0x0D:
            return True
        if t == 0x0E:
            return False
        if t == 0x0F:
            return self.u8()
        if t == 0x10:
            return self.num("h", 2)
        if t == 0x11:
            return self.num("i", 4)
        if t == 0x12:
            return self.num("q", 8)
        if t == 0x13:
            return self.num("f", 4)
        if t == 0x14:
            return self.num("d", 8)
        if t == 0x30:  # NSDate: seconds since 2001-01-01
            v = self.num("d", 8)
            self.objects.append(v)
            return v
        if t == 0x15:
            n = self.num("I", 4)
            b = self.d[self.p:self.p + n]
            self.p += n
            return b
        if t == 0x21:  # NSURL: string followed by base URL (usually nil terminator)
            v = self.value()
            base = self.value()
            return v if base is _END or base is None else str(base) + str(v)
        if 0x2C <= t <= 0x2F:  # small integer constants
            return t - 0x2D
        if t == 0x01:
            return None
        raise TSAFError("unknown type 0x%02x at %d" % (t, self.p - 1))


class _End:
    pass


_END = _End()


def decode(blob, strict=False):
    if not blob or blob[:4] != b"TSAF":
        raise TSAFError("not a TSAF blob")
    r = _Reader(blob)
    r.p = 20  # header: magic, version, counts
    try:
        return r.value()
    except (IndexError, TSAFError, struct.error, ValueError):
        if strict or not r.objects:
            raise
        return r.objects[0]  # partially decoded root object
