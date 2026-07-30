import struct
import re


class PTCDecoder:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    # =========================
    # BASIC READS
    # =========================
    def read_uint8(self):
        val = self.data[self.offset]
        self.offset += 1
        return val

    def read_uint16(self):
        val = struct.unpack(">H", self.data[self.offset:self.offset + 2])[0]
        self.offset += 2
        return val

    def read_uint32(self):
        val = struct.unpack(">I", self.data[self.offset:self.offset + 4])[0]
        self.offset += 4
        return val

    def read_bytes(self, n):
        val = self.data[self.offset:self.offset + n]
        self.offset += n
        return val

    def read_ascii(self, n):
        return self.read_bytes(n).decode("ascii", errors="ignore").rstrip("\x00")

    # =========================
    # TIME
    # =========================
    def parse_time(self):
        year = self.read_uint16()
        month = self.read_uint8()
        day = self.read_uint8()
        hour = self.read_uint8()
        minute = self.read_uint8()
        second = self.read_uint8()
        return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"

    # =========================
    # ENUMS
    # =========================
    def enum_crew(self, v):
        return {1: "No Action"}.get(v, f"Unknown({v})")

    def enum_reason(self, v):
        return {1: "New Authority"}.get(v, f"Unknown({v})")

    def enum_auth(self, v):
        return {1: "Track Warrant"}.get(v, f"Unknown({v})")

    def enum_bulletin(self, v):
        return {
            5: "Speed Restriction",
            8: "Track Out of Service"
        }.get(v, f"Unknown({v})")

    # =========================
    # HEADER
    # =========================
    def parse_header(self):
        h = {}
        h["protocol_version"] = self.read_uint8()
        h["message_id"] = self.read_uint16()
        h["message_version"] = self.read_uint8()
        h["flags"] = self.read_uint8()

        h["data_length"] = (
            self.read_uint8() << 16 |
            self.read_uint8() << 8 |
            self.read_uint8()
        )

        h["message_number"] = self.read_uint32()
        h["message_time"] = self.read_uint32()
        h["variable_header_size"] = self.read_uint8()
        h["ttl"] = self.read_uint16()
        h["qos"] = self.read_uint16()

        def read_null():
            s = self.offset
            while self.data[self.offset] != 0:
                self.offset += 1
            val = self.data[s:self.offset].decode("ascii")
            self.offset += 1
            return val

        h["source"] = read_null()
        h["destination"] = read_null()

        return h

    # =========================
    # SEGMENT
    # =========================
    def parse_segment(self, include_direction_dot=False):
        seg = {}

        seg["all_tracks"] = self.read_uint8()
        seg["start_mp"] = self.read_uint32() / 10000

        p = self.read_uint8()
        seg["start_prefix"] = self.read_ascii(p) if p else ""

        s = self.read_uint8()
        seg["start_suffix"] = self.read_ascii(s) if s else ""

        seg["end_mp"] = self.read_uint32() / 10000

        p = self.read_uint8()
        seg["end_prefix"] = self.read_ascii(p) if p else ""

        s = self.read_uint8()
        seg["end_suffix"] = self.read_ascii(s) if s else ""

        n = self.read_uint8()
        seg["track"] = self.read_ascii(n)

        seg["subdivision"] = self.read_uint16()

        if include_direction_dot:
            seg["direction"] = self.read_uint8()
            dot = self.read_ascii(7)
            seg["dot_id"] = dot.strip() if dot.strip() else ""

        return seg

    # =========================
    # CLEAN TEXT
    # =========================
    def clean_text(self, raw):
        text = raw.decode("ascii", errors="ignore")
        text = re.sub(r'[\x00-\x1F]+', '\n', text)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        lines = [re.sub(r'^[^A-Za-z0-9]+', '', l) for l in lines]
        return lines

    # =========================
    # 1041 (FINAL)
    # =========================
    def parse_1041(self):
        msg = {}
        msg["scac"] = self.read_ascii(4)

        sub_count = self.read_uint8()
        msg["subdivisions"] = []

        for _ in range(sub_count):
            sub = {}

            sub["id"] = self.read_uint16()
            sub["bulletin_type"] = self.enum_bulletin(self.read_uint8())
            sub["reference"] = self.read_uint32()

            l = self.read_uint8()
            sub["display_reference"] = self.read_ascii(l)

            speed_count = self.read_uint8()
            sub["speed_restrictions"] = []

            for _ in range(speed_count):
                sr = {}
                sr["speed"] = self.read_uint8()
                sr["train_type"] = self.read_uint8()
                sr["head_end"] = self.read_uint8()
                sr["restricted"] = self.read_uint8()
                sr["time_to_comply"] = self.read_uint8()

                sr["effective"] = self.parse_time()
                sr["expire"] = self.parse_time()

                tod = self.read_uint8()
                for _ in range(tod):
                    self.read_uint8()
                    self.read_bytes(3)
                    self.read_bytes(3)

                sub["speed_restrictions"].append(sr)

            # ✅ HANDLE REAL-WORLD TIMESTAMP
            if (
                self.offset + 2 < len(self.data)
                and self.data[self.offset] == 0
                and self.data[self.offset + 1] == 0x07
            ):
                self.offset += 1
                self.parse_time()

            # ✅ SKIP PADDING
            while self.offset < len(self.data) and self.data[self.offset] == 0:
                self.offset += 1

            # ✅ SEGMENTS
            seg_count = self.read_uint8()
            sub["segments"] = []

            for _ in range(seg_count):
                sub["segments"].append(self.parse_segment(include_direction_dot=True))

            # ✅ SUMMARY + LINES
            summary_len = self.read_uint8()
            sub["summary"] = self.read_ascii(summary_len)

            line_count = self.read_uint8()
            sub["lines"] = []

            for _ in range(line_count):
                l = self.read_uint8()
                sub["lines"].append(self.read_ascii(l))

            msg["subdivisions"].append(sub)

        return msg

    # =========================
    # 1051 (FINAL)
    # =========================
    def parse_1051(self):
        msg = {}

        msg["reason"] = self.enum_reason(self.read_uint8())
        msg["crew_action"] = self.enum_crew(self.read_uint8())
        msg["scac"] = self.read_ascii(4)

        msg["authority_number"] = self.read_uint32()

        l = self.read_uint8()
        msg["display_authority"] = self.read_ascii(l)

        msg["authority_type"] = self.enum_auth(self.read_uint8())

        sub_count = self.read_uint8()
        msg["subdivisions"] = []

        for _ in range(sub_count):
            sub = {}

            sub["id"] = self.read_uint16()
            sub["ok_time"] = self.parse_time()

            vc = self.read_uint8()
            sub["voids"] = [self.read_uint32() for _ in range(vc)]

            sc = self.read_uint16()

            sub["segments"] = []
            for _ in range(sc):
                start_offset = self.offset
                try:
                    seg = self.parse_segment(include_direction_dot=False)

                    # ✅ Validate segment (real MP range)
                    if not (0 <= seg["start_mp"] <= 1000 and 0 <= seg["end_mp"] <= 1000):
                        # rewind and stop (we hit text)
                        self.offset = start_offset
                        break

                    # ✅ Validate track name
                    if not seg["track"].isalpha():
                        self.offset = start_offset
                        break

                    sub["segments"].append(seg)

                except Exception:
                    self.offset = start_offset
                    break

            sub["track_crc"] = self.read_uint32()

            msg["subdivisions"].append(sub)

        # ✅ CLEAN RAW TEXT
        while self.offset < len(self.data) - 4 and self.data[self.offset] == 0:
            self.offset += 1

        raw = self.data[self.offset:-4]
        lines = self.clean_text(raw)

        msg["summary"] = lines[0] if lines else ""
        msg["lines"] = lines[1:] if len(lines) > 1 else []

        return msg

    # =========================
    # ENTRY
    # =========================
    def decode(self):
        result = {}
        result["header"] = self.parse_header()

        mid = result["header"]["message_id"]

        if mid == 1041:
            result["body"] = self.parse_1041()
        elif mid == 1051:
            result["body"] = self.parse_1051()
        else:
            result["body"] = {"error": "unsupported"}

        return result


# =========================
# TEST
# =========================
if __name__ == "__main__":
    hex_string = "040411061100012a000013886a28b42c26003b0030637378742e623a67622e686c00637378742e6c2e637378742e333339313a697463004353585401013e0800006d7d053238303239000007ea060911122f00000000000000000001020009b848024244000009ac900242440003534447013e01000000000000002932383032392054726b20426c6f636b656420202020534944494e4720545241434b20424c4f434b4544051f2020204c594f4e5356494c4c4520534944494e4720545241434b204254573a252020204d50204244202020202036332e372020202026204d50204244202020202036332e341b2020204f4e205344472054524b28532920495320424c4f434b4544392020203139204341525320572f452052525258203436303139392042442036332e3720452f4520435359582031323730342042442036332e3416202020202020202028203034204c494e452853292029aa2e2e1900000000d8c14278"

    data = bytes.fromhex(hex_string)

    decoder = PTCDecoder(data)
    import json
    print(json.dumps(decoder.decode(), indent=2))
