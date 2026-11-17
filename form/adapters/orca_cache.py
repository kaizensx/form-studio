"""Reader for OrcaSlicer's packed vendor preset caches (<vendor>.opc).

Since OrcaSlicer 2.5 the system presets are no longer JSON files under system/<vendor>/<kind>/.
Each vendor is one file, both in the program's shipped profiles and in <config>/system. The CLI
still takes presets as JSON, so this module reads a cache and gives each preset back as the same
key -> string / list-of-strings mapping a JSON preset has.

The layout is taken from OrcaSlicer's own source at tag v2.5.1, not guessed:

    src/libslic3r/PresetCacheFormat.cpp   file header, stamps, dictionary, entries
    src/libslic3r/Config.hpp              how each option type is archived, and its text form
    src/libslic3r/Preset.hpp              VendorProfile and its nested types
    docs/HLSD/preset-cache.md             the design

    header, 20 bytes, packed:  u32 magic "ZCRO" (0x4F52435A)  u32 format version
                               u64 body size (the rest of the file)  u32 CRC-32 of the body
    body, one cereal BinaryOutputArchive (raw native-endian values, nothing compressed;
    a string or vector is a u64 count followed by its elements):
        u32 format version, string vendor name, string vendor profile version
        dictionary: vector<string> option keys, vector<u16> option types, vector<string> enum names
        map<string, VendorProfile>
        process entries, filament entries, machine entries: u32 count, then per entry
            name, sub_path, config, inherits, includes, description, instantiation,
            setting_id, filament_id, renamed_from
        u64 parse error count
    config: u32 count, then per option a u16 dictionary index and the value by the type the
    dictionary recorded. Enums are u32 count + per value a u16 enum-name index (index 0 means
    "unnamed", and the raw i32 follows).

Only format version 2 is read. Any other version is refused by name rather than attempted.
Every cache OrcaSlicer has shipped so far was written on a little-endian machine, and that is
what is read here.

Numbers are archived as doubles and written back the way OrcaSlicer prints them (C++ stream
default, six significant digits), which is what its own JSON export produces.
"""
from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"ZCRO"
FORMAT_VERSION = 2
HEADER = struct.Struct("<4sIQI")            # magic, version, body size, crc32
KINDS = ("process", "filament", "machine")  # the order the three lists are written in

MAX_FILE = 256 * 1024 * 1024                # the largest shipped cache is a few MB
MAX_STAMP = 1024                            # vendor name / version (same bound as upstream)
MAX_ENTRIES = 0xFFFF                        # dictionary tables are indexed by u16

# ConfigOptionType (Config.hpp)
VECTOR = 0x4000
FLOAT, INT, STRING, PERCENT, FLOAT_OR_PERCENT, POINT, POINT3, BOOL, ENUM = 1, 2, 3, 4, 5, 6, 7, 8, 9
POINTS_GROUPS, INTS_GROUPS = 10 + VECTOR, 11 + VECTOR
INT_NIL = 0x7FFFFFFF                        # ConfigOptionIntsNullable::nil_value()
BOOL_NIL = 0xFF                             # ConfigOptionBoolsNullable::nil_value()
# OrcaSlicer writes these two string options to JSON escaped, every other string verbatim.
ESCAPED_STRINGS = {"bed_custom_texture", "bed_custom_model"}


class CacheError(ValueError):
    """The file is not a preset cache this reader can use."""


class CacheTooNew(CacheError):
    """A preset cache in a format version this reader does not know."""


@dataclass
class Preset:
    kind: str
    name: str
    inherits: str = ""
    config: dict = field(default_factory=dict)      # key -> str, or list[str] for vector options
    includes: list = field(default_factory=list)    # layered between the parent and this preset
    sub_path: str = ""
    description: str = ""
    instantiation: str = ""
    setting_id: str = ""
    filament_id: str = ""
    renamed_from: list = field(default_factory=list)

    def to_json(self) -> dict:
        """The preset as OrcaSlicer's JSON preset file states it (its own keys, nothing inherited)."""
        out = {"type": self.kind, "name": self.name}
        if self.inherits:
            out["inherits"] = self.inherits
        if self.includes:
            out["include"] = list(self.includes)
        out["from"] = "system"
        for key in ("setting_id", "filament_id", "instantiation", "description"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        out.update(self.config)
        return out


@dataclass
class Cache:
    path: str
    format_version: int
    vendor: str
    version: str
    presets: dict                                   # kind -> {name: Preset}
    models: list = field(default_factory=list)      # printer models from the vendor profile
    parse_errors: int = 0
    skipped: list = field(default_factory=list)     # option keys whose type this reader cannot print


def num(v: float) -> str:
    """A double the way a default C++ ostream prints it (%g, six significant digits)."""
    if v == 0:
        return "-0" if math.copysign(1.0, v) < 0 else "0"
    return "%g" % v


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.p = data, 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.p + n > len(self.d):
            raise CacheError("preset cache ends in the middle of a value (truncated or corrupt)")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def unpack(self, fmt: str):
        s = struct.Struct("<" + fmt)
        return s.unpack(self.take(s.size))

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return self.unpack("H")[0]

    def u32(self) -> int:
        return self.unpack("I")[0]

    def i32(self) -> int:
        return self.unpack("i")[0]

    def u64(self) -> int:
        return self.unpack("Q")[0]

    def f64(self) -> float:
        return self.unpack("d")[0]

    def count(self, width: int = 1) -> int:
        """A u64 element count. Each element takes at least `width` bytes, so a count the rest of
        the body cannot hold is refused before anything is allocated for it."""
        n = self.u64()
        if n * max(width, 1) > len(self.d) - self.p:
            raise CacheError("preset cache states a length larger than the file (corrupt)")
        return n

    def string(self, limit: int | None = None) -> str:
        n = self.count()
        if limit is not None and n > limit:
            raise CacheError("preset cache: string length out of bounds")
        return self.take(n).decode("utf-8", "replace")

    def strings(self) -> list:
        return [self.string() for _ in range(self.count(8))]

    def array(self, code: str, size: int) -> tuple:
        n = self.count(size)
        return struct.unpack(f"<{n}{code}", self.take(n * size))


def _float_or_percent(value: float, percent: bool) -> str:
    if math.isnan(value):
        return "nil"
    return num(value) + ("%" if percent else "")


def _value(r: _Reader, typ: int, enums: list):
    """One option value by its recorded type, as JSON text: str for a scalar, list[str] for a vector.
    Returns None for a type this reader has no text form for (after consuming nothing: it raises)."""
    if typ == FLOAT:
        return num(r.f64())
    if typ == INT:
        return str(r.i32())
    if typ == STRING:
        return r.string()
    if typ == PERCENT:
        return num(r.f64()) + "%"
    if typ == FLOAT_OR_PERCENT:
        v = r.f64()
        return _float_or_percent(v, bool(r.u8()))
    if typ == POINT:
        x, y = r.unpack("2d")
        return f"{num(x)},{num(y)}"
    if typ == POINT3:
        x, y, z = r.unpack("3d")
        return f"{num(x)},{num(y)},{num(z)}"
    if typ == BOOL:
        return "1" if r.u8() else "0"
    if typ == FLOAT + VECTOR:
        return ["nil" if math.isnan(v) else num(v) for v in r.array("d", 8)]
    if typ == INT + VECTOR:
        return ["nil" if v == INT_NIL else str(v) for v in r.array("i", 4)]
    if typ == STRING + VECTOR:
        return r.strings()
    if typ == PERCENT + VECTOR:
        return ["nil" if math.isnan(v) else num(v) + "%" for v in r.array("d", 8)]
    if typ == FLOAT_OR_PERCENT + VECTOR:
        out = []
        for _ in range(r.count(9)):
            v = r.f64()
            out.append(_float_or_percent(v, bool(r.u8())))
        return out
    if typ == POINT + VECTOR:
        n = r.count(16)                     # count of points; each is two doubles
        flat = struct.unpack(f"<{2 * n}d", r.take(16 * n))
        return [f"{num(flat[i])}x{num(flat[i + 1])}" for i in range(0, len(flat), 2)]
    if typ == BOOL + VECTOR:
        return ["nil" if v == BOOL_NIL else ("1" if v else "0") for v in r.array("B", 1)]
    if typ == POINTS_GROUPS:
        out = []
        for _ in range(r.count(8)):
            n = r.count(16)
            flat = struct.unpack(f"<{2 * n}d", r.take(16 * n))
            out.append(",".join(f"{num(flat[i])}x{num(flat[i + 1])}" for i in range(0, len(flat), 2)))
        return out
    if typ == INTS_GROUPS:
        return [",".join(str(v) for v in r.array("i", 4)) for _ in range(r.count(8))]
    if typ in (ENUM, ENUM + VECTOR):
        n = r.u32()
        if typ == ENUM and n != 1:
            raise CacheError("preset cache: a scalar enum carrying more than one value")
        if n * 2 > len(r.d) - r.p:
            raise CacheError("preset cache states a length larger than the file (corrupt)")
        out = []
        for _ in range(n):
            idx = r.u16()
            if idx >= len(enums):
                raise CacheError("preset cache: enum value index past the end of the dictionary")
            if idx == 0:                    # a value the writer could not name: the raw int follows
                raw = r.i32()
                out.append("nil" if raw == INT_NIL else str(raw))
            else:
                out.append(enums[idx])
        return out[0] if typ == ENUM else out
    raise CacheError(f"preset cache: option type {typ} is not one this reader knows")


def _config(r: _Reader, keys: list, types: list, enums: list) -> dict:
    out = {}
    n = r.u32()
    if n * 2 > len(r.d) - r.p:
        raise CacheError("preset cache states a length larger than the file (corrupt)")
    for _ in range(n):
        idx = r.u16()
        if idx >= len(keys):
            raise CacheError("preset cache: option index past the end of the dictionary")
        out[keys[idx]] = _value(r, types[idx], enums)
    return out


def _vendor_profiles(r: _Reader) -> list:
    """map<string, VendorProfile>. Only the printer models are kept; everything is consumed."""
    models = []
    for _ in range(r.count(8)):
        r.string()                                              # map key (vendor id)
        for _ in range(5):                                      # name, id, version, update url, changelog url
            r.string()
        for _ in range(r.count(8)):
            mid, name, model_id = r.string(), r.string(), r.string()
            r.u8()                                              # PrinterTechnology
            family = r.string()
            variants = [r.string() for _ in range(r.count(8))]
            materials, _unsupported_beds = r.strings(), r.strings()
            for _ in range(9):                                  # bed model, textures, hotend model
                r.string()
            models.append({"id": mid, "name": name, "model_id": model_id, "family": family,
                           "variants": variants, "default_materials": materials})
        r.strings()                                             # default_filaments (a set)
        r.strings()                                             # default_sla_materials (a set)
    return models


def read_header(data: bytes, path="") -> tuple:
    """(format version, body) after checking magic, version, size and CRC."""
    where = f" ({path})" if path else ""
    if len(data) < HEADER.size:
        raise CacheError(f"Not an OrcaSlicer preset cache: shorter than its 20-byte header{where}.")
    magic, version, size, crc = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise CacheError(f"Not an OrcaSlicer preset cache: the file does not start with ZCRO{where}.")
    if version != FORMAT_VERSION:
        newer = "a newer" if version > FORMAT_VERSION else "an older"
        raise CacheTooNew(f"This preset cache is format version {version}, {newer} format than the version "
                          f"{FORMAT_VERSION} Form Studio can read{where}. It was not read.")
    body = data[HEADER.size:]
    if size == 0 or size != len(body):
        raise CacheError(f"Preset cache is truncated or padded: the header states {size} body bytes, "
                         f"the file holds {len(body)}{where}.")
    if zlib.crc32(body) & 0xFFFFFFFF != crc:
        raise CacheError(f"Preset cache failed its CRC check; the file is damaged{where}.")
    return version, body


def parse(data: bytes, path="") -> Cache:
    version, body = read_header(data, path)
    r = _Reader(body)
    stamp = r.u32()
    if stamp != FORMAT_VERSION:
        raise CacheTooNew(f"This preset cache body is format version {stamp}; Form Studio reads version "
                          f"{FORMAT_VERSION}. It was not read.")
    vendor, vendor_version = r.string(MAX_STAMP), r.string(MAX_STAMP)
    keys = r.strings()
    types = list(r.array("H", 2))
    enums = r.strings()
    if len(keys) != len(types):
        raise CacheError("preset cache: dictionary key and type tables differ in length")
    if len(keys) > MAX_ENTRIES or len(enums) > MAX_ENTRIES:
        raise CacheError("preset cache: dictionary is larger than the uint16 it is indexed with")
    if not enums or enums[0] != "":
        raise CacheError("preset cache: dictionary is missing its unnamed-enum slot")
    cache = Cache(path=str(path), format_version=version, vendor=vendor, version=vendor_version,
                  presets={k: {} for k in KINDS})
    cache.models = _vendor_profiles(r)
    for kind in KINDS:
        n = r.u32()
        if n * 4 > len(body) - r.p:
            raise CacheError("preset cache states a length larger than the file (corrupt)")
        for _ in range(n):
            p = Preset(kind=kind, name=r.string(), sub_path=r.string())
            p.config = _config(r, keys, types, enums)
            p.inherits, p.includes, p.description = r.string(), r.strings(), r.string()
            p.instantiation, p.setting_id, p.filament_id = r.string(), r.string(), r.string()
            p.renamed_from = r.strings()
            cache.presets[kind][p.name] = p
    cache.parse_errors = r.u64()
    if r.p != len(body):
        raise CacheError("preset cache has bytes left over after its last field (corrupt)")
    return cache


_loaded: dict = {}      # path -> (mtime_ns, size, Cache | CacheError)


def read(path) -> Cache:
    """Read one <vendor>.opc. Raises CacheError (CacheTooNew for an unknown format version)."""
    path = Path(path)
    st = path.stat()
    if st.st_size > MAX_FILE:
        raise CacheError(f"Preset cache is {st.st_size} bytes, larger than any real one ({path}).")
    hit = _loaded.get(str(path))
    if hit and hit[:2] == (st.st_mtime_ns, st.st_size):
        result = hit[2]
    else:
        try:
            with open(path, "rb") as f:
                result = parse(f.read(MAX_FILE + 1), path)
        except CacheError as e:
            result = e
        _loaded[str(path)] = (st.st_mtime_ns, st.st_size, result)
    if isinstance(result, CacheError):
        raise result
    return result


def cache_files(dirs) -> list:
    """Every <vendor>.opc in the given folders, in folder order."""
    out = []
    for d in dirs:
        d = Path(d)
        if d.is_dir():
            out += sorted(d.glob("*.opc"))
    return out


LIBRARY = "OrcaFilamentLibrary"     # the one vendor every other vendor's presets may inherit from


def find(dirs, kind: str, name: str, within=None, prefer=None):
    """(Preset, cache path, problems): the cache carrying preset `name` of `kind`, or (None, None, problems).

    Parent names such as "fdm_process_common" exist in many vendors with different values, so
    where a preset is looked for matters, and follows OrcaSlicer (PresetBundle::resolve_vendor_preset):

      within=<cache path>  a parent or include of a preset from that cache: only that vendor's
                           cache, then the filament library. Never another vendor.
      prefer=<cache path>  a preset named by the person: that vendor first (the printer's), then
                           the library, then every other cache in folder order.

    A cache is only decoded when the name occurs in its bytes (strings are stored verbatim), so
    looking through the ~70 shipped vendors costs one read each. `problems` lists caches that
    held the name but could not be read, for the message shown to the person."""
    files = cache_files(dirs)
    first = Path(within or prefer) if (within or prefer) else None
    order = []
    if first is not None:
        order.append(first)
        order += [f for f in files if f.stem == LIBRARY and f.parent == first.parent]
        order += [f for f in files if f.stem == LIBRARY]
    if within is None:
        order += files
    needle, problems = name.encode("utf-8"), []
    for path in dict.fromkeys(order):
        try:
            if path.stat().st_size > MAX_FILE or needle not in path.read_bytes():
                continue
            preset = read(path).presets[kind].get(name)
        except CacheError as e:
            problems.append(str(e))
            continue
        except OSError as e:
            problems.append(f"{path}: {e}")
            continue
        if preset is not None:
            return preset, path, problems
    return None, None, problems
